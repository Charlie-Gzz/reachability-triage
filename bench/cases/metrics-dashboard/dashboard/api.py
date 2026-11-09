from fastapi import FastAPI, UploadFile

from dashboard.bands import composite

app = FastAPI()


@app.post("/satellite/composite")
async def satellite_composite(image: UploadFile, expression: str = "(a - b) / (a + b)"):
    data = await image.read()
    return {"png": composite(data, expression)}
