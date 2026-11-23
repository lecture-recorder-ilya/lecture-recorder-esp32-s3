import re
import torch
from torch import nn

ALPHABET = ' абвгдеёжзийклмнопрстуфхцчшщъыьэюяabcdefghijklmnopqrstuvwxyz0123456789'
TAGS = ('summary', 'homework', 'formula', 'subject', 'teacher')

def normalize(text):
    text = text.lower()
    return ' '.join(''.join(c if c in ALPHABET else ' ' for c in text).split())

def encode(text):
    return torch.tensor([ALPHABET.index(c)+1 for c in normalize(text)], dtype=torch.long)

def decode(ids):
    output, previous = [], -1
    for value in ids:
        value = int(value)
        if value and value != previous:
            output.append(ALPHABET[value-1])
        previous = value
    return ''.join(output).strip()

def features(audio):
    audio = torch.as_tensor(audio, dtype=torch.float32)
    spectrum = torch.stft(audio, 400, 160, window=torch.hann_window(400),
                          return_complex=True, center=True).abs().square()
    hz = torch.arange(201) * 40.0
    mel = lambda f: 2595 * torch.log10(1 + f/700)
    boundaries = 700*(10**(torch.linspace(mel(torch.tensor(40.)), mel(torch.tensor(7800.)), 82)/2595)-1)
    filters = torch.minimum((hz[None]-boundaries[:-2,None])/(boundaries[1:-1]-boundaries[:-2])[:,None],
                            (boundaries[2:,None]-hz[None])/(boundaries[2:]-boundaries[1:-1])[:,None]).clamp(min=0)
    result = (filters @ spectrum).clamp(min=1e-10).log().T
    return (result-result.mean())/result.std(unbiased=False).clamp(min=1)

class SpeechModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Conv1d(80, 96, 5, stride=2, padding=2)
        self.gru = nn.GRU(96, 128, num_layers=2, bidirectional=True, batch_first=True)
        self.head = nn.Linear(256, len(ALPHABET)+1)
    def forward(self, x):
        x = torch.relu(self.conv(x.T[None])).transpose(1,2)
        x, _ = self.gru(x)
        return self.head(x).log_softmax(-1).transpose(0,1)

class NotesModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(257, 48)
        self.gru = nn.GRU(48, 96, bidirectional=True, batch_first=True)
        self.head = nn.Linear(192, len(TAGS))
    def forward(self, text):
        if not text.strip():
            raise ValueError('Empty passage')
        values = list(text.encode('utf-8'))
        if len(values)>4096:
            raise ValueError('Passage too long; split it at a semantic boundary')
        ids = torch.tensor([v+1 for v in values], dtype=torch.long)[None]
        x, _ = self.gru(self.embedding(ids))
        return self.head(x.mean(dim=1))[0]
    def extract(self, passages, threshold=.5):
        result = {tag: [] for tag in TAGS}
        with torch.inference_mode():
            for text in passages:
                if not text.strip():continue
                for tag, score in zip(TAGS, self(text).sigmoid()):
                    if float(score)>=threshold:result[tag].append(text)
        return result

def edit_distance(reference, hypothesis):
    row = list(range(len(hypothesis)+1))
    for i, expected in enumerate(reference, 1):
        next_row = [i]
        for j, actual in enumerate(hypothesis, 1):
            next_row.append(min(row[j]+1, next_row[-1]+1, row[j-1]+(expected!=actual)))
        row = next_row
    return row[-1]
