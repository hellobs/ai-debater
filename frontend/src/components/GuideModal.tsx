/** 三分钟上手指南：新用户的第一次打开就有路可走。
 *  首次访问自动弹一次（localStorage 标记），之后点品牌旁的「?」再看。 */
import { useEffect, useState } from 'react'

const GUIDE_SEEN_KEY = 'debater.guideSeen'

export function shouldAutoShowGuide(): boolean {
  try {
    return !localStorage.getItem(GUIDE_SEEN_KEY)
  } catch {
    return false
  }
}

export default function GuideModal(props: { open: boolean; onClose: () => void }) {
  const { open, onClose } = props
  useEffect(() => {
    if (open) {
      try { localStorage.setItem(GUIDE_SEEN_KEY, '1') } catch { /* 隐私模式忽略 */ }
    }
  }, [open])
  // Esc 关闭：模态的标准键盘语义
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="guide-mask" onClick={onClose}>
      <section className="guide-card" onClick={(e) => e.stopPropagation()}>
        <header className="guide-head">
          <h3>三分钟上手</h3>
          <button className="btn-mini" onClick={onClose}>知道了</button>
        </header>

        <h4>现场 · 打比赛用（三个动作）</h4>
        <ol className="guide-list">
          <li>左侧选辩题、定立场，把<b>对方刚说的话</b>粘进输入框；</li>
          <li>点「生成参谋建议」——五路参谋并行出反驳、质询、逻辑、策略、风险（按钮旁有成本标注）；</li>
          <li>有用的点「采纳」进<b>我方论点台账</b>防立场漂移；法条引用自动核验，复盘可导出 Markdown / Word。</li>
        </ol>
        <p className="hint">自由辩论短兵相接：勾「快反模式」只跑反驳+风险两路，预算压到 8 秒。</p>

        <h4>备赛 · 六个板块</h4>
        <ul className="guide-list">
          <li><b>拆题台</b>——输入辩题秒出题型/主张/立论骨架；AI 深拆带判准攻防提示；<b>数据三连</b>把对方论点里的数据点逐个生成三连问。</li>
          <li><b>稿件生成</b>——引擎供料或 AI 供料，成稿预览带字数与朗读时长，导出 Markdown / Word。</li>
          <li><b>攻防演练</b>——抽真实交锋质询题自练，按题型筛选；被打穿进错题本优先重练。</li>
          <li><b>素材库</b>——87 个人物/事件例证带正反双向用法，按辩题贴题检索，一键送入稿件。</li>
          <li><b>人机对练</b>——你打一方 AI 打另一方，逐环节过招；质询环节 AI 只抛问题等你答；打完请教练点评。</li>
          <li><b>自动辩论</b>——看 AI 按完整赛制打一场，学各环节打法（12–18 次调用，开始前明示）。</li>
        </ul>

        <h4>成本红线</h4>
        <p className="hint">
          一切计费动作的按钮旁都标了次数，超时也计费；「探测」模型名与引用核验纯本地 0 消耗。
          接本地 Ollama 可整站零成本（见 README「本地模型」一节）。
        </p>
      </section>
    </div>
  )
}

/** 品牌旁的「?」入口：现场与备赛两处共用。 */
export function GuideEntry(props: { onOpen: () => void }) {
  const [hint, setHint] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setHint(true), 300)
    return () => clearTimeout(t)
  }, [])
  return (
    <button
      className="guide-entry"
      title="三分钟上手指南"
      onClick={props.onOpen}
    >
      ?{hint && <span className="guide-tip">上手指南</span>}
    </button>
  )
}
