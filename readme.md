## Create environment
```bash
python -m venv .venv
.venv\Scripts\activate
```

## Install packages

```bash
# GPU version of torch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Other requirements
pip install -r requirements.txt
```

## Jupyter

### Start Jupyter (web)

```bash
jupyter lab
```

> OR install Jupyter VSCode extension from Microsoft

## Verify CUDA

```python
import torch
print("Torch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("GPU:", torch.cuda.get_device_name(0))
```