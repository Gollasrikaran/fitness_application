from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import uvicorn
import torch
from TTS.api import TTS

app = FastAPI()

# Allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Automatically agree to Coqui's TOS to prevent the terminal from blocking
os.environ["COQUI_TOS_AGREED"] = "1"

# Check for GPU (CUDA). If you have an NVIDIA GPU, it will use it!
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Loading XTTSv2 Model on {device.upper()}... (This will download ~1.8GB of weights on first run!)")

# Load the Zero-Shot Cloning Model
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
print("✅ XTTSv2 Model Loaded and Ready!")

@app.post("/clone")
async def clone_voice(text: str = Form(...), speaker_wav: UploadFile = Form(...)):
    print(f"🎙️ Received Cloning Request! Text: '{text}'")
    
    # Save the 5-second audio sample from the frontend
    speaker_path = "temp_speaker.wav"
    with open(speaker_path, "wb") as f:
        f.write(await speaker_wav.read())
    
    output_path = "output_clone.wav"
    
    print("⚙️ Synthesizing Voice Clone...")
    # Generate the cloned audio!
    tts.tts_to_file(text=text, speaker_wav=speaker_path, language="en", file_path=output_path)
    
    print("✅ Done! Sending back to browser.")
    return FileResponse(output_path, media_type="audio/wav")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
