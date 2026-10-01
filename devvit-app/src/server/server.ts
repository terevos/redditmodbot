import {once} from 'node:events'
import type {IncomingMessage, ServerResponse} from 'node:http'
import type {
  OnModActionRequest,
  PartialJsonValue,
  TriggerResponse,
  UiResponse,
} from '@devvit/web/shared'
import {BadRequest, externalUrl, ops} from './ops.ts'
import {recordModAction} from './resolutions.ts'
import type {RpcError, RpcRequest} from './wire.ts'

// Must match devvit.json. `/external/` is reachable from outside with a managed
// app token, which Devvit checks before the request gets here; `/internal/` is
// only ever called by the platform.
const Route = {
  Rpc: '/external/rpc',
  OnModAction: '/internal/on/mod-action',
  OnAppInstall: '/internal/on/app/install',
  OnAppUpgrade: '/internal/on/app/upgrade',
  MenuEndpointUrl: '/internal/menu/endpoint-url',
} as const

export async function onReq(
  reqMsg: IncomingMessage,
  rspMsg: ServerResponse,
): Promise<void> {
  try {
    await route(reqMsg, rspMsg)
  } catch (err) {
    if (err instanceof BadRequest) {
      writeJson<RpcError>(400, {error: err.message, status: 400}, rspMsg)
      return
    }
    // Reddit's own failures land here too. 502 rather than 500: the bot backs
    // off on any 5xx, and this says the fault is upstream of the app.
    const msg = err instanceof Error ? err.message : `${err}`
    console.error(`server error; ${err instanceof Error ? err.stack : err}`)
    writeJson<RpcError>(502, {error: msg, status: 502}, rspMsg)
  }
}

async function route(
  reqMsg: IncomingMessage,
  rspMsg: ServerResponse,
): Promise<void> {
  const path = (reqMsg.url ?? '').split('?')[0]
  if (reqMsg.method !== 'POST') {
    writeJson<RpcError>(404, {error: 'not found', status: 404}, rspMsg)
    return
  }
  switch (path) {
    case Route.Rpc:
      writeJson(200, await routeRpc(await readJson<RpcRequest>(reqMsg)), rspMsg)
      return
    case Route.OnModAction:
      await recordModAction(await readJson<OnModActionRequest>(reqMsg))
      writeJson<TriggerResponse>(200, {}, rspMsg)
      return
    case Route.OnAppInstall:
    case Route.OnAppUpgrade:
      // The one place the URL is written down without a mod asking for it.
      console.log(`external URL: ${await externalUrl()}`)
      writeJson<TriggerResponse>(200, {}, rspMsg)
      return
    case Route.MenuEndpointUrl:
      writeJson<UiResponse>(200, {showToast: {text: await externalUrl()}}, rspMsg)
      return
    default:
      writeJson<RpcError>(404, {error: 'not found', status: 404}, rspMsg)
  }
}

export async function routeRpc(req: Readonly<RpcRequest>): Promise<PartialJsonValue> {
  const op = typeof req?.op === 'string' ? ops[req.op] : undefined
  if (!op || !Object.hasOwn(ops, req.op)) {
    throw new BadRequest(`unknown op ${JSON.stringify(req?.op)}`)
  }
  return (await op(req.args ?? {})) as PartialJsonValue
}

async function readJson<T>(reqMsg: IncomingMessage): Promise<T> {
  const chunks: Uint8Array[] = []
  reqMsg.on('data', chunk => chunks.push(chunk))
  await once(reqMsg, 'end')
  try {
    return JSON.parse(`${Buffer.concat(chunks)}`)
  } catch {
    throw new BadRequest('request body is not JSON')
  }
}

function writeJson<T extends PartialJsonValue>(
  status: number,
  json: Readonly<T>,
  rsp: ServerResponse,
): void {
  const body = JSON.stringify(json)
  rsp.writeHead(status, {
    'Content-Length': Buffer.byteLength(body),
    'Content-Type': 'application/json',
  })
  rsp.end(body)
}
