// Which posts and comments have been deleted.
//
// Reddit requires a copy of deleted content to go too, and the copies here are
// outside the app: the bot's store and the Slack cards. So the app only keeps
// the list — the delete triggers add to it, the bot reads it each poll and
// scrubs what it holds. IDs only; nothing about the content is recorded.

import {redis} from '@devvit/web/server'
import type {OnCommentDeleteRequest, OnPostDeleteRequest} from '@devvit/web/shared'
import {bareId} from './resolutions.ts'
import type {Deletions} from './wire.ts'

const KEY = 'deletions'
// The bot scrubs anything closed for 30 days regardless, so a deletion older
// than that has nothing left to remove.
const KEEP_MS = 30 * 24 * 60 * 60 * 1000
// One response's worth. A bot that was down for a while pages through.
const PAGE = 500

type DeleteEvent = OnPostDeleteRequest | OnCommentDeleteRequest

// EventSource.MODERATOR, which arrives as its number or its name.
function byModerator(source: unknown): boolean {
  return source === 3 || source === 'MODERATOR'
}

/**
 * The bare ID a delete event names, or undefined when it is not a deletion.
 *
 * A moderator's removal fires the same trigger, and is not one: the item is
 * still on Reddit, still its author's, and the mods are usually still talking
 * about it.
 */
export function deletedId(event: Readonly<DeleteEvent>): string | undefined {
  if (byModerator(event.source)) return undefined
  const id = event.type === 'CommentDelete' ? event.commentId : event.postId
  return id ? bareId(id) : undefined
}

export async function recordDeletion(
  event: Readonly<DeleteEvent>,
  now: number = Date.now(),
): Promise<void> {
  const id = deletedId(event)
  if (!id) return
  await redis.zAdd(KEY, {member: id, score: now})
}

/**
 * Deletions recorded after `since` (unix ms), oldest first. The caller passes
 * the returned `cursor` back as the next `since`.
 */
export async function deletionsSince(
  since: number,
  now: number = Date.now(),
): Promise<Deletions> {
  await redis.zRemRangeByScore(KEY, 0, now - KEEP_MS)
  // One past `since`: scores are whole milliseconds and the range is inclusive.
  const found = await redis.zRange(KEY, since + 1, Number.MAX_SAFE_INTEGER, {
    by: 'score',
    limit: {offset: 0, count: PAGE},
  })
  return {
    ids: found.map(f => f.member),
    cursor: found.length ? found[found.length - 1]!.score : since,
    more: found.length === PAGE,
  }
}
