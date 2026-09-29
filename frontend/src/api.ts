import type { AdvisorResult, AnalyzeInput, HealthInfo } from './types'

export async function fetchHealth(): Promise<HealthInfo> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`health ${res.status}`)
  return res.json()
}

/**
 * 用 SSE 订阅参谋结果。每完成一路就回调一次 onResult。
 * 返回一个取消函数。
 */
export function streamAnalyze(
  input: AnalyzeInput,
  onResult: (r: AdvisorResult) => void,
  onDone: (totalLatency: number) => void,
  onError: (msg: string) => void,
): () => void {
  const params = new URLSearchParams({
    topic: input.topic,
    our_side: input.our_side,
    opponent_text: input.opponent_text,
  })
  const es = new EventSource(`/api/analyze/stream?${params.toString()}`)

  es.addEventListener('advisor', (ev) => {
    try {
      onResult(JSON.parse((ev as MessageEvent).data))
    } catch {
      onError('结果解析失败')
    }
  })

  es.addEventListener('done', (ev) => {
    try {
      const d = JSON.parse((ev as MessageEvent).data)
      onDone(d.latency_s ?? 0)
    } catch {
      onDone(0)
    }
    es.close()
  })

  es.addEventListener('error', () => {
    // EventSource 在服务端正常关闭时也会触发 error；这里只在没收到 done 时提示
    onError('连接中断（后端或协议桥是否在运行？）')
    es.close()
  })

  return () => es.close()
}
