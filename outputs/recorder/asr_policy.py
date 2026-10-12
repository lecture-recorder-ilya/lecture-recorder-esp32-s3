def selected_model(selection, quality_available):
    if selection == 'auto':
        return 'qwen' if quality_available else 'whisper'
    if selection in ('qwen', 'whisper'):
        return selection
    raise ValueError('Неизвестная модель речи.')
