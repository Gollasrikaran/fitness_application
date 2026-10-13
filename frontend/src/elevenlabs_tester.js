const ELEVENLABS_API_KEY = import.meta.env.VITE_ELEVENLABS_API_KEY;

// Choose a default Voice ID for Vita. 
// "Sarah" (EXAVITQu4vr4xnSDxMaL) is an excellent free-tier default voice.
const VITA_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"; 

/**
 * Helper to encode Float32Array PCM data into a WAV Blob
 */
function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeString = (view, offset, string) => {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    };
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
        let s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return new Blob([buffer], { type: 'audio/wav' });
}

/**
 * Sends a recorded audio Float32Array to ElevenLabs Speech-to-Text API
 * Returns the transcribed string.
 */
export async function elevenlabsSTT(float32Array, sampleRate = 16000) {
    if (!ELEVENLABS_API_KEY) {
        throw new Error("Missing VITE_ELEVENLABS_API_KEY in .env.local");
    }

    const wavBlob = encodeWAV(float32Array, sampleRate);

    // Convert the audio Blob to a File object for the FormData
    const file = new File([wavBlob], "speech.wav", { type: "audio/wav" });
    const formData = new FormData();
    formData.append("file", file);
    formData.append("model_id", "scribe_v1");

    // Note: If ElevenLabs' official STT endpoint is different, update this URL.
    const res = await fetch("https://api.elevenlabs.io/v1/speech-to-text", {
        method: "POST",
        headers: {
            "xi-api-key": ELEVENLABS_API_KEY
        },
        body: formData
    });

    if (!res.ok) {
        const err = await res.text();
        console.error("ElevenLabs STT error:", err);
        throw new Error("Speech-to-Text failed: " + res.statusText);
    }

    const data = await res.json();
    return data.text;
}

/**
 * Sends text to ElevenLabs Text-to-Speech API
 * Downloads the MP3 and plays it instantly.
 * Returns a Promise that resolves when audio finishes playing.
 */
export async function elevenlabsTTS(text) {
    if (!ELEVENLABS_API_KEY) {
        throw new Error("Missing VITE_ELEVENLABS_API_KEY in .env.local");
    }

    const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${VITA_VOICE_ID}?output_format=mp3_44100_128`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        },
        body: JSON.stringify({
            text: text,
            model_id: "eleven_multilingual_v2",
            voice_settings: {
                stability: 0.5,
                similarity_boost: 0.75
            }
        })
    });

    if (!res.ok) {
        const err = await res.text();
        console.error("ElevenLabs TTS error:", err);
        throw new Error("Text-to-Speech failed: " + res.statusText);
    }

    // Convert response to a blob and play it
    const audioBlob = await res.blob();
    const audioUrl = URL.createObjectURL(audioBlob);
    const audio = new Audio(audioUrl);

    return new Promise((resolve, reject) => {
        audio.onended = () => {
            URL.revokeObjectURL(audioUrl);
            resolve();
        };
        audio.onerror = (e) => {
            URL.revokeObjectURL(audioUrl);
            reject(e);
        };
        audio.play().catch(reject);
    });
}
