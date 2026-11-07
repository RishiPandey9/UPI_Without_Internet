import uvicorn

if __name__ == "__main__":
    print("Starting UPI Without Internet (Python FastAPI) on http://localhost:8080...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
