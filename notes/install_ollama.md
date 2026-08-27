```
curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst -o ollama.tar.zst
mkdir ollama.new
tar --use-compress-program=zstd -xvf ollama.tar.zst -C ./ollama.new/
```