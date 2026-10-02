import assert from 'node:assert/strict'
import {once} from 'node:events'
import {createServer} from 'node:http'
import {test} from 'node:test'
import type {OnModActionRequest} from '@devvit/web/shared'
import {BadRequest, toConversation, toThing} from './ops.ts'
import {resolutionFromModAction} from './resolutions.ts'
import {onReq, routeRpc} from './server.ts'

type Item = Parameters<typeof toThing>[0]

function modAction(event: Partial<OnModActionRequest>): OnModActionRequest {
  return {type: 'ModAction', ...event} as OnModActionRequest
}

test('an approval is credited to the moderator who made it', () => {
  const found = resolutionFromModAction(
    modAction({
      action: 'approvelink',
      actionedAt: '2026-10-01T12:00:00Z',
      moderator: {name: 'terevos2'},
      targetPost: {id: 't3_abc'},
    } as Partial<OnModActionRequest>),
  )
  assert.deepEqual(found, {
    id: 'abc',
    resolution: {by: 'terevos2', action: 'approved', at: 1790856000},
  })
})

test('a comment action resolves the comment, not its parent post', () => {
  const found = resolutionFromModAction(
    modAction({
      action: 'spamcomment',
      moderator: {name: 'AutoModerator'},
      targetPost: {id: 't3_parent'},
      targetComment: {id: 't1_xyz'},
    } as Partial<OnModActionRequest>),
    5_000,
  )
  assert.deepEqual(found, {
    id: 'xyz',
    resolution: {by: 'AutoModerator', action: 'removed', at: 5},
  })
})

test('a mod action that settles nothing is ignored', () => {
  const event = modAction({action: 'lock', targetPost: {id: 't3_abc'}} as Partial<OnModActionRequest>)
  assert.equal(resolutionFromModAction(event), undefined)
})

test('a comment becomes a PRAW-shaped thing', () => {
  const comment = {
    id: 't1_c1',
    authorName: 'someuser',
    permalink: '/r/reformed/comments/p1/_/c1',
    createdAt: new Date(1_700_000_000_000),
    edited: false,
    body: 'hello',
    userReportReasons: ['Rule 2', 'Spam'],
    modReports: [{reason: 'check this', author: 'terevos2'}],
    approved: false,
    removed: false,
    spam: false,
  } as unknown as Item
  assert.deepEqual(toThing(comment), {
    id: 'c1',
    kind: 'comment',
    author: 'someuser',
    permalink: '/r/reformed/comments/p1/_/c1',
    created_utc: 1_700_000_000,
    edited: false,
    body: 'hello',
    user_reports: [['Rule 2', 1], ['Spam', 1]],
    mod_reports: [['check this', 'terevos2']],
    approved: false,
    removed: false,
    spam: false,
  })
})

test('a deleted author is null, and a post carries its title and url', () => {
  const post = {
    id: 't3_p1',
    authorName: '[deleted]',
    permalink: '/r/reformed/comments/p1/_/',
    createdAt: new Date(0),
    edited: true,
    title: 'A post',
    url: 'https://example.com/x',
    userReportReasons: [],
    modReports: [],
    approved: true,
    removed: false,
    spam: false,
  } as unknown as Item
  const thing = toThing(post)
  assert.equal(thing.kind, 'submission')
  assert.equal(thing.author, null)
  assert.equal(thing.title, 'A post')
  assert.equal(thing.url, 'https://example.com/x')
  assert.equal('body' in thing, false)
})

test('conversation messages come out oldest first, actions only on request', () => {
  const conv = {
    id: 'conv1',
    subject: 'Ban appeal',
    isAuto: false,
    state: 'Archived',
    authors: [],
    messages: {
      m2: {id: 'm2', author: {name: 'terevos2'}, bodyMarkdown: 'no', date: '2026-10-01T13:00:00Z'},
      m1: {id: 'm1', author: {name: 'someuser'}, bodyMarkdown: 'please', date: '2026-10-01T12:00:00Z'},
    },
    modActions: {
      a1: {actionType: 'Archived', date: '2026-10-01T13:01:00Z', author: {name: 'terevos2'}},
    },
  } as unknown as Parameters<typeof toConversation>[0]

  const listed = toConversation(conv, false)
  assert.deepEqual(listed.messages.map(m => m.id), ['m1', 'm2'])
  assert.equal('mod_actions' in listed, false)

  assert.deepEqual(toConversation(conv, true).mod_actions, [
    {action_type: 'Archived', date: '2026-10-01T13:01:00Z', author: 'terevos2'},
  ])
})

test('an unknown op is a bad request, including an inherited property name', async () => {
  await assert.rejects(routeRpc({op: 'nope'}), BadRequest)
  await assert.rejects(routeRpc({op: 'constructor'}), BadRequest)
})

test('a missing argument is a bad request before Reddit is asked', async () => {
  await assert.rejects(routeRpc({op: 'item', args: {kind: 'comment'}}), BadRequest)
  await assert.rejects(routeRpc({op: 'item', args: {id: 'abc', kind: 'post'}}), BadRequest)
})

test('an install succeeds even when the external URL cannot be read', async () => {
  // Outside Devvit there is no context, so reading the URL throws — the same
  // shape as an app that has not been granted external endpoints.
  const server = createServer(onReq).listen(0)
  await once(server, 'listening')
  const {port} = server.address() as {port: number}
  try {
    for (const path of ['/internal/on/app/install', '/internal/on/app/upgrade', '/internal/menu/endpoint-url']) {
      const rsp = await fetch(`http://localhost:${port}${path}`, {method: 'POST', body: '{}'})
      assert.equal(rsp.status, 200, path)
    }
  } finally {
    server.close()
  }
})
