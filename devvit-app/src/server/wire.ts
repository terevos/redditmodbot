// The JSON the Python bot and this app exchange over /external/rpc.
//
// Field names are snake_case and mirror what PRAW exposed, because the Python
// side (devvit_reddit.py) rebuilds PRAW-shaped objects from them and the bot's
// own code reads those. Changing a name here is a change to that file too.

/** One call. `op` picks the handler; `args` is that handler's input. */
export type RpcRequest = {
  op: string
  args?: Record<string, unknown>
}

export type RpcError = {error: string; status: number}

export type ThingKind = 'comment' | 'submission'

/** A post or comment, as a modqueue entry or a fetched item. */
export type Thing = {
  /** Bare ID, without the `t1_` / `t3_` prefix. */
  id: string
  kind: ThingKind
  /** `null` for a deleted author. */
  author: string | null
  /** Site-relative, e.g. `/r/reformed/comments/abc/…`. */
  permalink: string
  created_utc: number
  edited: boolean
  /** Comments only. */
  body?: string
  /** Submissions only. */
  title?: string
  url?: string
  /** `[reason, count]`. Devvit reports reasons without counts, so count is 1. */
  user_reports: [string, number][]
  /** `[reason, moderator]`. */
  mod_reports: [string, string][]
  approved: boolean
  removed: boolean
  spam: boolean
}

/**
 * A fetched item, plus who resolved it. Devvit's models carry no `approved_by`
 * / `banned_by`; these come from the resolutions this app records itself (see
 * resolutions.ts). At most one is set — whichever action came last.
 */
export type ResolvedThing = Thing & {
  approved_by: string | null
  banned_by: string | null
}

export type ModmailMessage = {
  id: string
  /** `null` for a deleted author. */
  author: string | null
  body_markdown: string
  /** ISO-8601. */
  date: string
}

export type ModmailAction = {
  /** Devvit's name for it: `Archived`, `Unarchived`, `Muted`, … */
  action_type: string
  /** ISO-8601. */
  date: string
  author: string
}

export type ModmailConversation = {
  id: string
  subject: string
  is_auto: boolean
  state: string
  /** Oldest first. A listing may carry only the newest message. */
  messages: ModmailMessage[]
  /** Present only on a conversation fetched by ID, never in a listing. */
  mod_actions?: ModmailAction[]
}

export type RemovalReason = {id: string; title: string; message: string}

/** A resolution recorded from a mod action, or looked up in the mod log. */
export type Resolution = {
  /** Moderator username; `''` when the lookup found nobody to name. */
  by: string
  action: 'approved' | 'removed'
  /** Unix seconds. */
  at: number
}
