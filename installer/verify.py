import gc
import sys
from pathlib import Path

root = Path(sys.argv[1])
mode = sys.argv[2]
sys.path.insert(0, str(root / 'outputs/recorder'))
models = root / 'work/models'
if mode == 'recorder':
    import serial
    import ssl
    import phone_pairing
    import study_store
    import update_manager
    for source in (root / 'outputs/recorder').glob('*.py'):
        compile(source.read_bytes(), str(source), 'exec')
    assert sys.version_info[:2] == (3, 12)
elif mode == 'ai':
    import mlx.core as mx
    import mlx_whisper
    import mlx_lm
    import onnxruntime
    import onnx_asr
    import pymorphy3
    import torch
    from speech_gate import speech_profile
    from transformers import AutoTokenizer, AutoModel, AutoFeatureExtractor, WavLMForXVector
    torch.set_num_threads(1)
    assert not speech_profile(torch.zeros(16000).numpy()).strict
    for folder, name in [('gigaam', 'v3_e2e_ctc.int8.onnx'), ('gigaam-rnnt', 'v3_e2e_rnnt_encoder.onnx'),
                         ('gigaam-rnnt', 'v3_e2e_rnnt_decoder.onnx'), ('gigaam-rnnt', 'v3_e2e_rnnt_joint.onnx'),
                         ('gigaam-beam', 'v3_ctc.onnx')]:
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1
        session = onnxruntime.InferenceSession(str(models / folder / name), sess_options=options, providers=['CPUExecutionProvider'])
        assert session.get_inputs()
        del session
        gc.collect()
    model, tokenizer = mlx_lm.load(str(models / 'lecture'), lazy=True)
    assert tokenizer.encode('Лекция')
    del model, tokenizer
    gc.collect()
    mx.clear_cache()
    from mlx_whisper.load_models import load_model
    model = load_model(str(models / 'whisper'), dtype=mx.float16)
    del model
    gc.collect()
    mx.clear_cache()
    tokenizer = AutoTokenizer.from_pretrained(str(models / 'search'), local_files_only=True)
    model = AutoModel.from_pretrained(str(models / 'search'), local_files_only=True)
    del model, tokenizer
    gc.collect()
    model = WavLMForXVector.from_pretrained(str(models / 'speakers'), local_files_only=True)
    extractor = AutoFeatureExtractor.from_pretrained(str(models / 'speakers'), local_files_only=True)
    del model, extractor
elif mode == 'vision':
    import mlx_vlm
    import torchvision
    from PIL import Image
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(str(models / 'board-vision'), local_files_only=True, trust_remote_code=False)
    assert processor is not None
    model, processor = mlx_vlm.load(str(models / 'board-vision'), lazy=True, trust_remote_code=False)
    assert model is not None and processor is not None
else:
    raise ValueError('Unknown verification mode')
print('Verified:', mode)
