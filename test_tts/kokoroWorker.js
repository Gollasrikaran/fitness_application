import { KokoroTTS } from "https://cdn.jsdelivr.net/npm/kokoro-js@1.1.1/dist/kokoro.web.js";

let tts = null;

self.onmessage = async (e) => {
    const { type, payload } = e.data;

    try {
        if (type === 'init') {
            if (!tts) {
                // Initialize the WASM model in the background thread!
                tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
                    dtype: 'q8'
                });
            }
            self.postMessage({ type: 'ready' });
        } 
        else if (type === 'generate') {
            const { text, voice } = payload;
            
            // Run heavy WASM inference in background thread
            const out = await tts.generate(text, { voice: voice });
            
            // Send the raw Float32Array back to the main UI thread for playback
            self.postMessage({ 
                type: 'audio', 
                audioData: out.audio, 
                sampleRate: out.sampling_rate 
            });
        }
    } catch (error) {
        self.postMessage({ type: 'error', message: error.message });
    }
};
