// Push-to-talk in the page: record the microphone, make a mono 16-bit WAV at 16 kHz, and give it to the service (which sends it to the voice model). Nothing is
// kept: the recording lives in memory until it is sent. The pure parts (resample, encodeWav, toBase64) are tested without a browser.
export const RATE = 16000;

export function resample(samples, fromRate, toRate = RATE) {
  if (fromRate === toRate) return Float32Array.from(samples);
  const length = Math.max(1, Math.floor((samples.length * toRate) / fromRate));
  const out = new Float32Array(length);
  const ratio = fromRate / toRate;
  for (let i = 0; i < length; i += 1) {
    const at = i * ratio, low = Math.floor(at), high = Math.min(samples.length - 1, low + 1), frac = at - low;
    out[i] = samples[low] * (1 - frac) + samples[high] * frac;
  }
  return out;
}

export function encodeWav(samples, rate = RATE) {
  const bytes = new Uint8Array(44 + samples.length * 2);
  const view = new DataView(bytes.buffer);
  const text = (at, s) => { for (let i = 0; i < s.length; i += 1) bytes[at + i] = s.charCodeAt(i); };
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return bytes;
}

export function toBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** Records while held. start() asks for the microphone; stop() resolves {wavBase64, seconds}. The browser asks the person for permission. */
export class Recorder {
  constructor(env = globalThis) {
    this.env = env;
    this.chunks = [];
    this.stream = null;
    this.context = null;
    this.node = null;
  }

  async start() {
    this.stream = await this.env.navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
    const Ctx = this.env.AudioContext || this.env.webkitAudioContext;
    this.context = new Ctx();
    const source = this.context.createMediaStreamSource(this.stream);
    this.node = this.context.createScriptProcessor(4096, 1, 1);
    this.node.onaudioprocess = (event) => this.chunks.push(Float32Array.from(event.inputBuffer.getChannelData(0)));
    source.connect(this.node);
    this.node.connect(this.context.destination);
  }

  async stop() {
    const rate = this.context ? this.context.sampleRate : RATE;
    if (this.node) this.node.disconnect();
    if (this.stream) for (const track of this.stream.getTracks()) track.stop();
    if (this.context) await this.context.close();
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const all = new Float32Array(total);
    let at = 0;
    for (const c of this.chunks) { all.set(c, at); at += c.length; }
    this.chunks = [];
    const wav = encodeWav(resample(all, rate));
    return { wavBase64: toBase64(wav), seconds: total / rate };
  }
}
