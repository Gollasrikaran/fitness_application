import { pipeline, env } from '@huggingface/transformers';

// Disable local cache check to force downloading from HF hub
env.allowLocalModels = false;

let transcriber = null;

self.onmessage = async (event) => {
    const { type, audioData, useWebGPU } = event.data;
    
    if (type === 'init') {
        try {
            self.postMessage({ status: 'loading' });
            
            transcriber = await pipeline('automatic-speech-recognition', 'Xenova/whisper-base.en', {
                device: useWebGPU ? 'webgpu' : 'wasm',
                progress_callback: (data) => {
                    self.postMessage({ status: 'progress', data });
                }
            });
            
            self.postMessage({ status: 'ready' });
        } catch (err) {
            self.postMessage({ status: 'error', error: err.message });
        }
    } else if (type === 'transcribe') {
        try {
            self.postMessage({ status: 'inferring' });
            
            const start = performance.now();
            
            // audioData must be a Float32Array at 16kHz mono
            const result = await transcriber(audioData, {
                chunk_length_s: 30,
                stride_length_s: 5,
            });
            
            const end = performance.now();
            const timeMs = end - start;
            const audioSeconds = audioData.length / 16000;
            const words = result.text.trim().split(/\s+/).length;
            const speedup = audioSeconds / (timeMs / 1000);
            
            self.postMessage({ 
                status: 'done', 
                text: result.text,
                timeMs: timeMs,
                audioSeconds: audioSeconds,
                speedup: speedup,
                wordsPerSec: words / (timeMs / 1000)
            });
        } catch (err) {
            self.postMessage({ status: 'error', error: err.message });
        }
    }
};
