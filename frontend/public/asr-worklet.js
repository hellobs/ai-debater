// 采集 PCM 的 AudioWorklet 处理器：把每帧 Float32 采样抛给主线程。
// 只做搬运不做 DSP——单声道、降噪等由 getUserMedia 约束负责，
// 重采样由 AudioContext 的 sampleRate 选项负责（主线程按实际 rate 上报）。
class PcmRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel) this.port.postMessage(channel)
    return true
  }
}
registerProcessor('pcm-recorder', PcmRecorder)
