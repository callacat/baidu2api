import httpx, asyncio
async def t():
    c=httpx.AsyncClient(timeout=30)
    r=await c.post("http://localhost:8000/v1/chat/completions",
        json={"model":"deepseek-v4-pro","messages":[{"role":"user","content":"用中文回答：你是谁？"}],"stream":False},
        headers={"Authorization":"Bearer sk-dijiaozhibei"})
    d=r.json()
    t=d["choices"][0]["message"]["content"]
    print(f"content_len={len(t)} chars={len(t.encode('utf-8'))} bytes")
    print("RAW:", repr(t[:100]))
    print("TEXT:", t)
    await c.aclose()
asyncio.run(t())
