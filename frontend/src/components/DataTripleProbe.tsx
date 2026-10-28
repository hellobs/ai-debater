/** 数据三连：粘贴一段论点 → 本地抽出数据点 → 每个给基数/口径/来源三连问。
 *  观摩实战（2026-10-25）的教训产品化：「64%」四口径无人追问。纯本地正则，0 消耗。
 *  拆题台（备赛常驻）与现场速查（模态）共用；「送入对练」只在拆题台出现。 */
import { useState } from 'react'
import { extractDataPoints, tripleProbe } from '../prep/engine'

export default function DataTripleProbe(props: { withSparring?: boolean }) {
  const { withSparring = false } = props
  const [text, setText] = useState('')
  const [copied, setCopied] = useState(false)
  const [sent, setSent] = useState(false)
  const points = text.trim() ? extractDataPoints(text).slice(0, 8) : []
  const fullText = points
    .map((dp, i) => {
      const probes = tripleProbe(dp)
      return `数据点 ${i + 1}：${dp.raw}\n${probes.map((p, j) => `  ${'一二三'[j]}、${p}`).join('\n')}`
    })
    .join('\n\n')

  const copyText = () => {
    void navigator.clipboard?.writeText(fullText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const sendToSparring = () => {
    try {
      localStorage.setItem('debater.sparringSeed', JSON.stringify({ stage: '质询与小结', text: fullText }))
      window.dispatchEvent(new CustomEvent('debater.sparring-handoff'))
      setSent(true)
      setTimeout(() => setSent(false), 2000)
    } catch { /* 隐私模式忽略 */ }
  }

  return (
    <div>
      <textarea
        className="text-input"
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="粘贴对方论点原文，例：斯坦福研究显示 64% 的创作者支持 AI 训练，Google 已支付 6000 万美元授权费……"
      />
      {points.length === 0 && text.trim() && (
        <p className="muted">没扫到数据点——没有数字的论点，直接攻它的逻辑链。</p>
      )}
      {points.length > 0 && (
        <>
          {points.map((dp, i) => (
            <div className="split-block" key={i}>
              <h4>数据点 {i + 1}：{dp.raw}</h4>
              <ul>{tripleProbe(dp).map((p, j) => <li key={j}>{p}</li>)}</ul>
            </div>
          ))}
          <div className="prep-actions">
            <button className="btn-mini" title="复制全部三连问" onClick={copyText}>
              {copied ? '✓ 已复制' : '复制三连问'}
            </button>
            {withSparring && (
              <button
                className="btn-mini"
                title="送入「人机对练」的质询环节，拿 AI 实操这些追问"
                onClick={sendToSparring}
              >
                {sent ? '✓ 已送入' : '送入对练'}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
