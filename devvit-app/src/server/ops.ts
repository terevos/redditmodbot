// The Reddit operations the bot can ask for, one per `op` name.
//
// This is the whole of what replaced PRAW: every call reddit_actions.py used
// to make through it has a handler here. Each runs as the app account, in the
// subreddit the request's install belongs to — there is no subreddit argument,
// because an install only ever acts on its own.

import {
  type Comment,
  context,
  externalEndpoints,
  type Post,
  reddit,
} from '@devvit/web/server'
import {bareId, getResolution} from './resolutions.ts'
import type {
  ModmailAction,
  ModmailConversation,
  ModmailMessage,
  RemovalReason,
  ResolvedThing,
  Thing,
  ThingKind,
} from './wire.ts'

/** A request the caller got wrong: unknown op, missing or mistyped argument. */
export class BadRequest extends Error {}

type Args = Readonly<Record<string, unknown>>
type Op = (args: Args) => Promise<unknown>

// Reddit's own default page for these listings, and PRAW's default limit.
const DEFAULT_LIMIT = 100

function str(args: Args, name: string): string {
  const value = args[name]
  if (typeof value !== 'string' || !value) {
    throw new BadRequest(`"${name}" must be a non-empty string`)
  }
  return value
}

function optStr(args: Args, name: string): string | undefined {
  const value = args[name]
  if (value === undefined || value === null || value === '') return undefined
  if (typeof value !== 'string') throw new BadRequest(`"${name}" must be a string`)
  return value
}

function optNum(args: Args, name: string): number | undefined {
  const value = args[name]
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new BadRequest(`"${name}" must be a number`)
  }
  return value
}

function kindOf(args: Args): ThingKind {
  const kind = args.kind
  if (kind !== 'comment' && kind !== 'submission') {
    throw new BadRequest('"kind" must be "comment" or "submission"')
  }
  return kind
}

function commentId(id: string): `t1_${string}` {
  return `t1_${bareId(id)}`
}

function postId(id: string): `t3_${string}` {
  return `t3_${bareId(id)}`
}

async function fetchThing(args: Args): Promise<Post | Comment> {
  const id = str(args, 'id')
  return kindOf(args) === 'comment'
    ? reddit.getCommentById(commentId(id))
    : reddit.getPostById(postId(id))
}

function isComment(item: Post | Comment): item is Comment {
  return item.id.startsWith('t1_')
}

/** A deleted account reads as `[deleted]`; the bot wants that as "no author". */
function authorOrNull(name: string | undefined): string | null {
  return !name || name === '[deleted]' ? null : name
}

export function toThing(item: Post | Comment): Thing {
  const common = {
    id: bareId(item.id),
    author: authorOrNull(item.authorName),
    permalink: item.permalink,
    created_utc: Math.floor(item.createdAt.getTime() / 1000),
    edited: item.edited,
    user_reports: item.userReportReasons.map((reason): [string, number] => [reason, 1]),
    mod_reports: item.modReports.map((r): [string, string] => [r.reason, r.author]),
    approved: item.approved,
    removed: item.removed,
    spam: item.spam,
  }
  return isComment(item)
    ? {...common, kind: 'comment', body: item.body}
    : {...common, kind: 'submission', title: item.title, url: item.url}
}

type RawConversation = Awaited<
  ReturnType<typeof reddit.modMail.getConversations>
>['conversations'][string]

export function toConversation(
  conv: RawConversation,
  withActions: boolean,
): ModmailConversation {
  const messages: ModmailMessage[] = Object.entries(conv.messages ?? {})
    .map(([id, m]) => ({
      id: m.id ?? id,
      author: m.author?.isDeleted ? null : authorOrNull(m.author?.name),
      body_markdown: m.bodyMarkdown ?? '',
      date: m.date ?? '',
    }))
    // ISO-8601, so string order is time order.
    .sort((a, b) => a.date.localeCompare(b.date))
  const out: ModmailConversation = {
    id: conv.id ?? '',
    subject: conv.subject ?? '',
    is_auto: conv.isAuto ?? false,
    state: conv.state ?? '',
    messages,
  }
  if (withActions) {
    out.mod_actions = Object.values(conv.modActions ?? {}).map(
      (a): ModmailAction => ({
        action_type: a.actionType,
        date: a.date ?? '',
        author: a.author?.name ?? '',
      }),
    )
  }
  return out
}

/**
 * The ops a caller may actually run. A leaked token can do whatever the app
 * can, so the app can do only what the bot uses: read the queue and modmail,
 * and archive or unarchive a conversation. Everything that posts, comments,
 * removes, bans or messages stays written below but is refused — the bot's
 * matching controls are dormant too, and reviving one is adding its op here.
 */
export const ENABLED_OPS: ReadonlySet<string> = new Set([
  'info',
  'moderators',
  'modqueue',
  'item',
  'modmail_conversations',
  'modmail_conversation',
  'modmail_archive',
  'modmail_unarchive',
])

export const ops: {[name: string]: Op} = {
  /** Liveness and identity: which install answered, and where it lives. */
  async info() {
    return {
      subreddit: context.subredditName,
      subreddit_id: context.subredditId,
      app: context.appSlug,
      version: context.appVersion,
      external_url: await externalUrl(),
    }
  },

  async moderators() {
    const mods = await reddit
      .getModerators({subredditName: context.subredditName})
      .all()
    return {names: mods.map(m => m.username)}
  },

  async modqueue(args) {
    const limit = optNum(args, 'limit') ?? DEFAULT_LIMIT
    const items = await reddit
      .getModQueue({subreddit: context.subredditName, type: 'all', limit})
      .all()
    return {items: items.map(toThing)}
  },

  /** One post or comment by ID, with who approved or removed it. */
  async item(args): Promise<{item: ResolvedThing}> {
    const item = await fetchThing(args)
    const thing = toThing(item)
    const removed = thing.removed || thing.spam
    const resolution = await getResolution(item.id, context.subredditName, {
      approved: thing.approved,
      removed,
    })
    let approvedBy: string | null = null
    let bannedBy: string | null = null
    if (resolution?.action === 'approved') approvedBy = resolution.by || null
    if (resolution?.action === 'removed') bannedBy = resolution.by || null
    // A post names its own remover, which covers a removal nothing recorded.
    if (!resolution && removed && !isComment(item)) bannedBy = item.removedBy ?? null
    return {item: {...thing, approved_by: approvedBy, banned_by: bannedBy}}
  },

  async approve(args) {
    await (await fetchThing(args)).approve()
    return {}
  },

  async remove(args) {
    await (await fetchThing(args)).remove(args.spam === true)
    return {}
  },

  async ignore_reports(args) {
    await (await fetchThing(args)).ignoreReports()
    return {}
  },

  async distinguish(args) {
    const item = await fetchThing(args)
    if (isComment(item)) await item.distinguish(args.sticky === true)
    else await item.distinguish()
    return {}
  },

  /** Reply to a post or comment as the app, optionally distinguished. */
  async reply(args) {
    const item = await fetchThing(args)
    const text = str(args, 'text')
    const reply = isComment(item)
      ? await item.reply({text})
      : await item.addComment({text})
    if (args.distinguish === true) await reply.distinguish(args.sticky === true)
    return {id: bareId(reply.id), permalink: reply.permalink}
  },

  async removal_reasons(): Promise<{reasons: RemovalReason[]}> {
    const reasons = await reddit.getSubredditRemovalReasons(context.subredditName)
    return {reasons: reasons.map(r => ({id: r.id, title: r.title, message: r.message}))}
  },

  async ban(args) {
    await reddit.banUser({
      subredditName: context.subredditName,
      username: str(args, 'username'),
      reason: optStr(args, 'reason'),
      note: optStr(args, 'note'),
      duration: optNum(args, 'duration'),
    })
    return {}
  },

  async unban(args) {
    await reddit.unbanUser(str(args, 'username'), context.subredditName)
    return {}
  },

  /**
   * A modmail listing. As with Reddit's own API, a listed conversation carries
   * no mod actions — fetch it with `modmail_conversation` for those.
   */
  async modmail_conversations(args) {
    const state = optStr(args, 'state') ?? 'all'
    const rsp = await reddit.modMail.getConversations({
      subreddits: [context.subredditName],
      state: state as NonNullable<Parameters<typeof reddit.modMail.getConversations>[0]['state']>,
      limit: optNum(args, 'limit') ?? DEFAULT_LIMIT,
      sort: 'recent',
    })
    const ordered = rsp.conversationIds.length
      ? rsp.conversationIds
      : Object.keys(rsp.conversations)
    const conversations: ModmailConversation[] = []
    for (const id of ordered) {
      const conv = rsp.conversations[id]
      if (conv) conversations.push(toConversation({...conv, id: conv.id ?? id}, false))
    }
    return {conversations}
  },

  /** One conversation in full: every message, and its mod actions. */
  async modmail_conversation(args) {
    const id = str(args, 'id')
    const rsp = await reddit.modMail.getConversation({conversationId: id})
    if (!rsp.conversation) throw new BadRequest(`no such conversation ${id}`)
    return {conversation: toConversation({...rsp.conversation, id: rsp.conversation.id ?? id}, true)}
  },

  async modmail_archive(args) {
    await reddit.modMail.archiveConversation(str(args, 'id'))
    return {}
  },

  async modmail_unarchive(args) {
    await reddit.modMail.unarchiveConversation(str(args, 'id'))
    return {}
  },

  async modmail_reply(args) {
    await reddit.modMail.reply({
      conversationId: str(args, 'id'),
      body: str(args, 'body'),
      isAuthorHidden: args.author_hidden === true,
    })
    return {}
  },

  async modmail_mute(args) {
    const hours = optNum(args, 'hours') ?? 72
    if (hours !== 72 && hours !== 168 && hours !== 672) {
      throw new BadRequest('"hours" must be 72, 168 or 672')
    }
    await reddit.modMail.muteConversation({conversationId: str(args, 'id'), numHours: hours})
    return {}
  },

  /** Start a modmail conversation with a user, from the subreddit. */
  async modmail_create(args) {
    const rsp = await reddit.modMail.createConversation({
      subredditName: context.subredditName,
      subject: str(args, 'subject'),
      body: str(args, 'body'),
      to: str(args, 'to'),
      isAuthorHidden: true,
    })
    return {id: rsp.conversation.id ?? ''}
  },
}

/** The root `/external/` URL of this install — the bot's DEVVIT_URL. */
export async function externalUrl(): Promise<string> {
  return externalEndpoints.getExternalUrl({
    appSlug: context.appSlug,
    locationId: context.subredditId,
  })
}
