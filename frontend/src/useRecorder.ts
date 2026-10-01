import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 流式收音 hook（UX-3 二期）：WebSocket + AudioWorklet，**边说边出字**。
 *
 * 与一期批式的分工：批式（POST /api/asr/transcribe）是"整段录完再转"，
 * 现场要盯着空白输入框干等；流式把识别搬进会话——服务端按端点检测自动
 * 分段（说完停顿 ~2.4s 切一段），partial 实时滚动，结束后全文已就位，
 * 手动步骤从五步压到两步（结束 → 生成）。
 *
 * 协议见后端 `POST /api/asr/stream` 旁的 docstring：
 * partial = 当前段实时文本；segment = 已完成的段；final = stop 后的尾段。
 * 全文 = segments 依次拼接 + final。
 *
 * 浏览器端同样全部用原生能力：AudioWorklet 采集、AudioContext 的
 * sampleRate 选项让浏览器重采样到 16k，每 ~8ms 一帧转 Int16 直接上送。
 */
export interface StreamResult {
  /** 收音期间累计的全文（segments + final）。可能为空串（没说出话）。 */
  text: string
}

type AsrState = 'idle' | 'starting' | 'listening' | 'stopping' | 'error'

/** 单段收音上限（秒）。超时自动停，防忘点「结束」。 */
const MAX_SECONDS = 600
/** stop 后等服务端 final 的上限。超时就用已收到的 segments + partial 兜底。 */
const FINAL_TIMEOUT_MS = 8000

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/asr/stream`
}

export function useRecorder() {
  const [state, setState] = useState<AsrState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0) // 0~1 峰值电平，「正在收音」的肉眼确认
  const [partial, setPartial] = useState('')
  const [segments, setSegments] = useState<string[]>([])
  const [error, setError] = useState('')

  const ctxRef = useRef<AudioContext | null>(null)
  const mediaRef = useRef<MediaStream | null>(null)
  const nodeRef = useRef<AudioWorkletNode | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const rateRef = useRef(16000)
  const startedAtRef = useRef(0)
  const lastLevelAtRef = useRef(0)
  /** stop 是异步的，防重入；也防 stop 与 onclose 清理互相踩。 */
  const stoppingRef = useRef(false)
  /** 服务端消息里已经收完（final 已到 / 连接已断），之后的 onclose 不算错误。 */
  const doneRef = useRef(false)
  const segmentsRef = useRef<string[]>([])
  const partialRef = useRef('')
  /** stop() 等待 final 帧的兑现器。 */
  const finalResolveRef = useRef<((text: string) => void) | null>(null)
  /** 超时自动停的定时器也要能摸到 stop；ref 破解 start→stop 的循环依赖。 */
  const stopRef = useRef<(() => Promise<StreamResult | null>) | null>(null)

  const teardown = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    nodeRef.current?.disconnect(); nodeRef.current = null
    mediaRef.current?.getTracks().forEach((t) => t.stop()); mediaRef.current = null
    void ctxRef.current?.close().catch(() => { /* 关不掉就算了 */ })
    ctxRef.current = null
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
      wsRef.current.close()
    }
    wsRef.current = null
    setLevel(0)
  }, [])

  // 组件卸载时必须交还麦克风并断开 ws
  useEffect(() => teardown, [teardown])

  const start = useCallback(async (): Promise<boolean> => {
    if (state === 'listening' || state === 'starting' || state === 'stopping') return false
    setError('')
    setPartial('')
    setSegments([])
    segmentsRef.current = []
    partialRef.current = ''
    doneRef.current = false
    setState('starting')
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('此浏览器不支持麦克风采集：需要 Chrome/Edge，并通过 localhost 或 HTTPS 访问')
      setState('error')
      return false
    }
    try {
      // 1) 麦克风（不开回声消除：收的是现场人声，不是通话回音）
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      // 2) 采集 → 16k 单声道 PCM
      const ctx = new AudioContext({ sampleRate: 16000 })
      await ctx.audioWorklet.addModule('/asr-worklet.js')
      const node = new AudioWorkletNode(ctx, 'pcm-recorder')
      rateRef.current = ctx.sampleRate
      // 3) WebSocket（先建连接，onopen 后再接管音频，避免话音丢进未就绪的 ws）
      const ws = new WebSocket(wsUrl())
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'config', sample_rate: rateRef.current }))
        startedAtRef.current = performance.now()
        setElapsed(0)
        timerRef.current = setInterval(() => {
          const sec = (performance.now() - startedAtRef.current) / 1000
          setElapsed(sec)
          if (sec >= MAX_SECONDS) void stopRef.current?.()
        }, 200)
        setState('listening')
      }
      ws.onmessage = (ev) => {
        let data: { type: string; text?: string; reason?: string }
        try { data = JSON.parse(ev.data as string) } catch { return }
        if (data.type === 'partial') {
          partialRef.current = data.text ?? ''
          setPartial(partialRef.current)
        } else if (data.type === 'segment') {
          const seg = data.text ?? ''
          if (seg) {
            segmentsRef.current.push(seg)
            setSegments([...segmentsRef.current])
          }
          partialRef.current = ''
          setPartial('')
        } else if (data.type === 'final') {
          doneRef.current = true
          const tail = data.text ?? ''
          finalResolveRef.current?.(segmentsRef.current.join('') + tail)
          finalResolveRef.current = null
        } else if (data.type === 'error') {
          doneRef.current = true
          setError(data.reason ?? '转写服务返回错误')
          setState('error')
          finalResolveRef.current?.('')
          finalResolveRef.current = null
          teardown()
        }
      }
      ws.onclose = () => {
        // stop 正常收尾 / error 分支已处理过；只有**意外断开**才算错误。
        if (!doneRef.current) {
          doneRef.current = true
          setError('转写服务连接中断（后端在跑吗？）')
          setState('error')
          finalResolveRef.current?.('')
          finalResolveRef.current = null
          teardown()
        }
      }
      ws.onerror = () => { /* onclose 会跟着来，那里统一处理 */ }

      const source = ctx.createMediaStreamSource(stream)
      source.connect(node)
      // 刻意不连 destination：处理器没有输出，连上反而可能把采集的声音外放
      node.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const chunk = ev.data
        let peak = 0
        for (let i = 0; i < chunk.length; i += 4) { // 隔 4 个采样看电平就够
          const v = Math.abs(chunk[i])
          if (v > peak) peak = v
        }
        const now = performance.now()
        if (now - lastLevelAtRef.current >= 100) { // 电平条 10Hz，别把面板刷爆
          lastLevelAtRef.current = now
          setLevel(peak)
        }
        if (ws.readyState === WebSocket.OPEN) {
          // Float32 → Int16（后端按 16bit 小端解析）
          const out = new Int16Array(chunk.length)
          for (let i = 0; i < chunk.length; i++) {
            const s = Math.max(-1, Math.min(1, chunk[i]))
            out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
          }
          ws.send(out.buffer)
        }
      }

      ctxRef.current = ctx
      mediaRef.current = stream
      nodeRef.current = node
      // 'starting' → ws.onopen 里转 'listening'（麦克风权限和服务端就绪都过了才算开录）
      return true
    } catch (e) {
      teardown()
      const name = (e as DOMException)?.name
      setError(
        name === 'NotAllowedError'
          ? '麦克风权限被拒绝：请在浏览器地址栏允许后重试'
          : name === 'NotFoundError'
            ? '没有找到可用的麦克风设备'
            : `无法开始收音：${String(e)}`,
      )
      setState('error')
      return false
    }
  }, [state, teardown])

  const stop = useCallback(async (): Promise<StreamResult | null> => {
    const ws = wsRef.current
    if (state !== 'listening' || stoppingRef.current || !ws) return null
    stoppingRef.current = true
    setState('stopping')
    try {
      const text = await new Promise<string>((resolve) => {
        finalResolveRef.current = resolve
        try { ws.send(JSON.stringify({ type: 'stop' })) } catch { resolve('') }
        // final 超时兜底：用已收到的内容收尾，不让用户干等
        setTimeout(() => {
          finalResolveRef.current?.(segmentsRef.current.join('') + partialRef.current)
          finalResolveRef.current = null
        }, FINAL_TIMEOUT_MS)
      })
      doneRef.current = true
      teardown()
      setState('idle')
      setPartial('')
      setSegments([])
      segmentsRef.current = []
      if (!text.trim()) {
        setError('这段没有识别到内容（对方没开口？）')
        return { text: '' }
      }
      return { text }
    } finally {
      stoppingRef.current = false
    }
  }, [state, teardown])

  const cancel = useCallback(() => {
    doneRef.current = true
    teardown()
    setPartial('')
    setSegments([])
    segmentsRef.current = []
    setState('idle')
    setElapsed(0)
  }, [teardown])

  useEffect(() => { stopRef.current = stop })

  return {
    state,
    listening: state === 'listening',
    stopping: state === 'stopping',
    elapsed,
    level,
    /** 边说边出字的实时全文（已完成段 + 当前段） */
    liveText: segments.join('') + partial,
    error,
    start,
    stop,
    cancel,
  }
}
