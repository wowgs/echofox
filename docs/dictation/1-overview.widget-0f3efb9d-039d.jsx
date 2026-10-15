export default () => {
  const ink = 'var(--cds-text-primary)', quiet = 'var(--cds-text-secondary)', edge = 'var(--cds-chart-axis)', accent = 'var(--cds-chart-categorical-1)';
  const mx = 24, mw = 496, sx = 552, sw = 184;
  const box = (x, y, w, h, main) => <rect x={x} y={y} width={w} height={h} rx='8' fill={main ? accent : 'none'} fillOpacity={main ? 0.12 : 1} stroke={main ? accent : edge} strokeWidth={main ? 2 : 1.25}/>;
  return <svg viewBox='0 0 760 488' role='img' aria-label='Sound goes from the microphone through the client and the server to the model; text comes back to the input box' fontSize='13'>
    <defs><marker id='pipe-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M0 0L10 5L0 10z' fill={edge}/></marker></defs>
    <text data-claude-text-id='title' x='24' y='28' fontSize='15' fontWeight='600' fill={ink}>Звук идёт вниз к модели, текст возвращается в поле ввода</text>
    <g data-claude-anchor='webview'>{box(mx, 48, mw, 72, false)}
      <text data-claude-text-id='webview-name' x={mx + 12} y='72' fontWeight='600' fill={ink}>Поле ввода любого приложения</text>
      <text data-claude-text-id='webview-1' x={mx + 12} y='88' fontSize='11.5' fill={quiet}>Сюда приходит текст расшифровки.</text>
      <text data-claude-text-id='webview-2' x={mx + 12} y='104' fontSize='11.5' fill={quiet}>Вставляет его клиент (вкладка 5).</text>
    </g>
    <g data-claude-anchor='host'>{box(mx, 160, mw, 88, false)}
      <text data-claude-text-id='host-name' x={mx + 12} y='184' fontWeight='600' fill={ink}>Клиент: приложение в строке меню (план)</text>
      <text data-claude-text-id='host-1' x={mx + 12} y='200' fontSize='11.5' fill={quiet}>Микрофон: 16 кГц, 16 бит, моно.</text>
      <text data-claude-text-id='host-2' x={mx + 12} y='216' fontSize='11.5' fill={quiet}>Шлёт имя модели, сессии или приложение и звук.</text>
      <text data-claude-text-id='host-3' x={mx + 12} y='232' fontSize='11.5' fill={quiet}>Показывает текст; стоп по тишине — по событиям speech.</text>
    </g>
    <g data-claude-anchor='server'>{box(mx, 288, mw, 88, true)}
      <text data-claude-text-id='server-name' x={mx + 12} y='312' fontWeight='600' fill={ink}>Сервер gemma_voice.py (launchd, порт 8090)</text>
      <text data-claude-text-id='server-1' x={mx + 12} y='328' fontSize='11.5' fill={quiet}>После стопа режет звук на равные куски около 20 с.</text>
      <text data-claude-text-id='server-2' x={mx + 12} y='344' fontSize='11.5' fill={quiet}>Одна запись за раз; каждый кусок — отдельный запрос.</text>
      <text data-claude-text-id='server-3' x={mx + 12} y='360' fontSize='11.5' fill={quiet}>Реестр моделей, контекст чата, все файлы записи.</text>
    </g>
    <g data-claude-anchor='model'>{box(mx, 416, mw, 56, false)}
      <text data-claude-text-id='model-name' x={mx + 12} y='440' fontWeight='600' fill={ink}>llama-server (порт 8092) и Gemma 4 E4B</text>
      <text data-claude-text-id='model-1' x={mx + 12} y='456' fontSize='11.5' fill={quiet}>GGUF Q8_0, все слои на GPU; звук 25 токенов/с, до 30 с.</text>
    </g>
    <g data-claude-anchor='jsonl'>{box(sx, 160, sw, 72, false)}
      <text data-claude-text-id='jsonl-name' x={sx + 12} y='184' fontWeight='600' fill={ink}>JSONL сессии</text>
      <text data-claude-text-id='jsonl-1' x={sx + 12} y='200' fontSize='11.5' fill={quiet}>~/.claude/projects/…</text>
      <text data-claude-text-id='jsonl-2' x={sx + 12} y='216' fontSize='11.5' fill={quiet}>только мои итоговые ответы</text>
    </g>
    <g data-claude-anchor='recordings'>{box(sx, 288, sw, 88, false)}
      <text data-claude-text-id='rec-name' x={sx + 12} y='312' fontWeight='600' fill={ink}>~/speech/recordings</text>
      <text data-claude-text-id='rec-1' x={sx + 12} y='328' fontSize='11.5' fill={quiet}>звук и тексты записи;</text>
      <text data-claude-text-id='rec-2' x={sx + 12} y='344' fontSize='11.5' fill={quiet}>твоя правка рядом:</text>
      <text data-claude-text-id='rec-3' x={sx + 12} y='360' fontSize='11.5' fill={quiet}>correction.json</text>
    </g>
    <g data-claude-anchor='connectors' fill='none' stroke={edge} strokeWidth='1.25'>
      <path d='M200 120V160' markerEnd='url(#pipe-arrow)'/>
      <path d='M200 248V288' markerEnd='url(#pipe-arrow)'/>
      <path d='M200 376V416' markerEnd='url(#pipe-arrow)'/>
      <path d='M420 416V376' markerEnd='url(#pipe-arrow)'/>
      <path d='M420 288V248' markerEnd='url(#pipe-arrow)'/>
      <path d='M420 160V120' markerEnd='url(#pipe-arrow)'/>
      <path d={`M${sx} 216H536V312H${mx + mw}`} markerEnd='url(#pipe-arrow)'/>
      <path d={`M${mx + mw} 352H${sx}`} markerEnd='url(#pipe-arrow)'/>
    </g>
    <text data-claude-text-id='down-1' x='208' y='144' fontSize='11.5' fill={quiet}>запись</text>
    <text data-claude-text-id='down-2' x='208' y='272' fontSize='11.5' fill={quiet}>start, звук, stop</text>
    <text data-claude-text-id='down-3' x='208' y='400' fontSize='11.5' fill={quiet}>текст, звук куска</text>
    <text data-claude-text-id='up-3' x='428' y='400' fontSize='11.5' fill={quiet}>текст куска</text>
    <text data-claude-text-id='up-2' x='428' y='272' fontSize='11.5' fill={quiet}>text, done</text>
    <text data-claude-text-id='up-1' x='428' y='144' fontSize='11.5' fill={quiet}>текст в поле</text>
  </svg>;
};
