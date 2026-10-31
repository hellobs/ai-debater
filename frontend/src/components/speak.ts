/** 浏览器 TTS 朗读（Web Speech API，纯本地 0 消耗）：现场眼睛盯比赛，耳朵听建议。
 *  长文本按句切段顺序播（绕开部分平台对单次 utterance 的时长截断）。 */

let currentChunks: SpeechSynthesisUtterance[] = []

/** 是否有可用的中文语音（无 zh voice 的环境读中文会变成无声/拼音腔——如实降级为不朗读）。 */
export function ttsAvailable(): boolean {
  try {
    return typeof window !== 'undefined' && 'speechSynthesis' in window &&
      window.speechSynthesis.getVoices().some((v) => v.lang.toLowerCase().startsWith('zh'))
  } catch {
    return false
  }
}

/** 朗读一段文本（自动停止前一次）。返回是否成功启动。 */
export function speak(text: string): boolean {
  if (!text.trim() || !ttsAvailable()) return false
  stopSpeaking()
  const synth = window.speechSynthesis
  const zhVoice = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith('zh'))
  // 按句切：句号/问号/叹号/分号/换行，段最长 120 字（再长按长度硬切）
  const raw = text.replace(/\s+/g, ' ').split(/(?<=[。？！；\n])/)
  const chunks: string[] = []
  for (const seg of raw) {
    const s = seg.trim()
    if (!s) continue
    if (s.length <= 120) chunks.push(s)
    else for (let i = 0; i < s.length; i += 120) chunks.push(s.slice(i, i + 120))
  }
  currentChunks = chunks.map((c) => {
    const u = new SpeechSynthesisUtterance(c)
    if (zhVoice) u.voice = zhVoice
    u.lang = 'zh-CN'
    u.rate = 1.1
    return u
  })
  for (const u of currentChunks) synth.speak(u)
  return currentChunks.length > 0
}

/** 停止朗读。 */
export function stopSpeaking(): void {
  try { window.speechSynthesis?.cancel() } catch { /* 忽略 */ }
  currentChunks = []
}

/** 是否正在朗读（供按钮切换「朗读/停止」）。 */
export function isSpeaking(): boolean {
  try { return !!window.speechSynthesis?.speaking } catch { return false }
}
