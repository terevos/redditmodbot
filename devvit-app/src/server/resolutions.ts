// Who approved or removed an item.
//
// PRAW read this off the item (`approved_by`, `banned_by`); Devvit's Post and
// Comment models do not carry it. So the app keeps its own record, written by
// the onModAction trigger as each action happens, and the bot's "who resolved
// this?" becomes one Redis read instead of a Reddit fetch.

import {reddit, redis} from '@devvit/web/server'
import type {OnModActionRequest} from '@devvit/web/shared'
import type {Resolution} from './wire.ts'

/** Mod-log action names that settle an item, and what each one means. */
const RESOLVING_ACTIONS: {[action: string]: Resolution['action']} = {
  approvelink: 'approved',
  approvecomment: 'approved',
  removelink: 'removed',
  removecomment: 'removed',
  spamlink: 'removed',
  spamcomment: 'removed',
}

// The bot stops asking about an item long before this (it re-asks a closed
// card for at most a few days), so the record only needs to outlive that.
const RECORD_TTL_MS = 30 * 24 * 60 * 60 * 1000
// How long "the mod log names nobody" is believed before it is looked up
// again. The bot re-asks about an unresolved item on every poll; without this
// each of those would cost a mod-log listing.
const MISS_TTL_MS = 10 * 60 * 1000
// How far back the mod-log fallback looks, per action type.
const MOD_LOG_DEPTH = 100

function recordKey(bareId: string): string {
  return `resolution:${bareId}`
}

function missKey(bareId: string): string {
  return `resolution-miss:${bareId}`
}

export function bareId(id: string): string {
  return id.replace(/^t[0-9]_/, '')
}

/** What a mod action resolves, or undefined when it resolves nothing. */
export function resolutionFromModAction(
  event: Readonly<OnModActionRequest>,
  now: number = Date.now(),
): {id: string; resolution: Resolution} | undefined {
  const action = RESOLVING_ACTIONS[event.action ?? '']
  if (!action) return undefined
  // A comment action can carry the parent post as well, so the action name —
  // not which target happens to be present — says what was acted on.
  const target = event.action?.endsWith('comment')
    ? event.targetComment?.id
    : event.targetPost?.id
  if (!target) return undefined
  const at = event.actionedAt ? Date.parse(event.actionedAt) : now
  return {
    id: bareId(target),
    resolution: {
      by: event.moderator?.name ?? '',
      action,
      at: Math.floor((Number.isNaN(at) ? now : at) / 1000),
    },
  }
}

/** Record a mod action, if it is one that resolves an item. */
export async function recordModAction(
  event: Readonly<OnModActionRequest>,
): Promise<void> {
  const found = resolutionFromModAction(event)
  if (!found) return
  await redis.set(recordKey(found.id), JSON.stringify(found.resolution), {
    expiration: new Date(Date.now() + RECORD_TTL_MS),
  })
  await redis.del(missKey(found.id))
}

/**
 * Who resolved an item, from the record or — for an action that predates the
 * install, or a trigger that never arrived — from the mod log.
 *
 * `state` is what the item itself says happened; the mod log is only searched
 * when it says something did, so an item still sitting in the queue costs
 * nothing here.
 */
export async function getResolution(
  fullId: string,
  subredditName: string,
  state: {approved: boolean; removed: boolean},
): Promise<Resolution | undefined> {
  const id = bareId(fullId)
  const recorded = await redis.get(recordKey(id))
  if (recorded) return JSON.parse(recorded) as Resolution
  if (!state.approved && !state.removed) return undefined
  if (await redis.get(missKey(id))) return undefined

  const found = await findInModLog(fullId, subredditName, state)
  if (found) {
    await redis.set(recordKey(id), JSON.stringify(found), {
      expiration: new Date(Date.now() + RECORD_TTL_MS),
    })
  } else {
    await redis.set(missKey(id), '1', {
      expiration: new Date(Date.now() + MISS_TTL_MS),
    })
  }
  return found
}

async function findInModLog(
  fullId: string,
  subredditName: string,
  state: {approved: boolean; removed: boolean},
): Promise<Resolution | undefined> {
  const link = fullId.startsWith('t3_')
  const types = state.removed
    ? ([link ? 'removelink' : 'removecomment', link ? 'spamlink' : 'spamcomment'] as const)
    : ([link ? 'approvelink' : 'approvecomment'] as const)
  let latest: Resolution | undefined
  for (const type of types) {
    const entries = await reddit
      .getModerationLog({subredditName, type, limit: MOD_LOG_DEPTH, pageSize: MOD_LOG_DEPTH})
      .all()
    for (const entry of entries) {
      if (entry.target?.id !== fullId) continue
      const at = Math.floor(entry.createdAt.getTime() / 1000)
      if (!latest || at > latest.at) {
        latest = {by: entry.moderatorName, action: RESOLVING_ACTIONS[type]!, at}
      }
    }
  }
  return latest
}
