import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 现场录音 hook：采集 16bit 单声道 PCM，交给 /api/asr/transcribe 转写。
 *
 * 设计取「手动分闸」：对方开口点开始、说完点结束——现场只有两三个人说话，
 * 人手一按就能区分谁在发言，不值得引入说话人分离。转写由调用方决定何时发起，
 * 本 hook 只负责采到一段干净的字节流。
 *
 * 浏览器端全部用现代原生能力：AudioWorklet（Chrome 66+）采集，
 * AudioContext 的 sampleRate 选项让浏览器自己重采样到 16k（后端认 16k，
 * 采样率不符时sherpa-onnx 也会内部重采样，这里取实际值上报即可）。
 */
export interface RecorderResult {
  pcm: ArrayBuffer
  sampleRate: number
  durationS: number
}

type RecorderState = 'idle' | 'starting' | 'recording' | 'error'

/** 单段收音上限（秒）。现场单段发言不会这么长，超时自动停是防忘点「结束」。 */
const MAX_SECONDS = 600

export function useRecorder() {
  const [state, setState] = useState<RecorderState>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [level, setLevel] = useState(0) // 0~1 峰值电平，给界面的「正在收音」确认
  const [error, setError] = useState('')

  const ctxRef = useRef<AudioContext | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const nodeRef = useRef<AudioWorkletNode | null>(null)
  const chunksRef = useRef<Float32Array[]>([])
  const rateRef = useRef(16000)
  const startedAtRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  /** stop 是异步的，期间可能被快速双击——用标志位防重入。 */
  const stoppingRef = useRef(false)
  /** 超时自动停的定时器回调也要能摸到 stop；ref 破解 start→stop 的循环依赖。 */
  const stopRef = useRef<(() => Promise<RecorderResult | null>) | null>(null)

  const teardown = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    nodeRef.current?.disconnect(); nodeRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null
    void ctxRef.current?.close().catch(() => { /* 关不掉就算了 */ })
    ctxRef.current = null
    setLevel(0)
  }, [])

  // 组件卸载时必须交还麦克风，否则浏览器的「正在使用」红标一直挂着
  useEffect(() => teardown, [teardown])

  const start = useCallback(async (): Promise<boolean> => {
    if (state === 'recording' || state === 'starting') return false
    setError('')
    setState('starting')
    if (!navigator.mediaDevices?.getUserMedia) {
      // 局域网以 http://IP 访问时正是这个分支：安全上下文里 getUserMedia 不存在
      setError('此浏览器不支持麦克风采集：需要 Chrome/Edge，并通过 localhost 或 HTTPS 访问')
      setState('error')
      return false
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          // 不开回声消除：收的是现场的人声，不是通话回音；开着反而可能吃掉远端语音
          echoCancellation: false,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })
      const ctx = new AudioContext({ sampleRate: 16000 })
      await ctx.audioWorklet.addModule('/asr-worklet.js')
      const node = new AudioWorkletNode(ctx, 'pcm-recorder')
      node.port.onmessage = (ev: MessageEvent<Float32Array>) => {
        const chunk = ev.data
        chunksRef.current.push(chunk)
        let peak = 0
        for (let i = 0; i < chunk.length; i += 4) { // 隔 4 个采样看一眼电平就够
          const v = Math.abs(chunk[i])
          if (v > peak) peak = v
        }
        setLevel(peak)
      }
      ctx.resume().catch(() => { /* 有的浏览器要手势后 resume；点击链路里通常已就绪 */ })
      const source = ctx.createMediaStreamSource(stream)
      source.connect(node)
      // 刻意不连 destination：处理器没有输出，连上反而可能把采集到的声音外放

      ctxRef.current = ctx
      streamRef.current = stream
      nodeRef.current = node
      chunksRef.current = []
      rateRef.current = ctx.sampleRate
      startedAtRef.current = performance.now()
      setElapsed(0)
      timerRef.current = setInterval(() => {
        const sec = (performance.now() - startedAtRef.current) / 1000
        setElapsed(sec)
        if (sec >= MAX_SECONDS) void stopRef.current?.()
      }, 200)
      setState('recording')
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

  const stop = useCallback(async (): Promise<RecorderResult | null> => {
    if (state !== 'recording' || stoppingRef.current) return null
    stoppingRef.current = true
    try {
      const chunks = chunksRef.current
      const durationS = (performance.now() - startedAtRef.current) / 1000
      const sampleRate = rateRef.current
      teardown()
      setState('idle')
      chunksRef.current = []
      if (!chunks.length || durationS < 0.3) {
        setError('这段太短了（不足 0.3 秒），没有转写')
        return null
      }
      // 合并 Float32 → 削波 → Int16（后端按 16bit 小端解析）
      let total = 0
      for (const c of chunks) total += c.length
      const out = new Int16Array(total)
      let off = 0
      for (const c of chunks) {
        for (let i = 0; i < c.length; i++) {
          const s = Math.max(-1, Math.min(1, c[i]))
          out[off++] = s < 0 ? s * 0x8000 : s * 0x7fff
        }
      }
      return { pcm: out.buffer, sampleRate, durationS }
    } finally {
      stoppingRef.current = false
    }
  }, [state, teardown])

  const cancel = useCallback(() => {
    teardown()
    chunksRef.current = []
    setState('idle')
    setElapsed(0)
  }, [teardown])

  useEffect(() => { stopRef.current = stop })

  return { state, recording: state === 'recording', elapsed, level, error, start, stop, cancel }
}
