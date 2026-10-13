import { pipeline, env } from 'https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2';

env.allowLocalModels = false;
let synthesizer = null;

self.onmessage = async (e) => {
    const { type, payload } = e.data;

    try {
        if (type === 'init') {
            if (!synthesizer) {
                // Downloading the official Hindi model for MMS-TTS!
                synthesizer = await pipeline('text-to-speech', 'Xenova/mms-tts-hin');
            }
            self.postMessage({ type: 'ready' });
        } 
        else if (type === 'generate') {
            const out = await synthesizer(payload.text);
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
