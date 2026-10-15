export default () => {
  const ink = 'var(--cds-text-primary)', quiet = 'var(--cds-text-secondary)', edge = 'var(--cds-chart-axis)', accent = 'var(--cds-chart-categorical-1)';
  const box = (x, y, w, h, main) => <rect x={x} y={y} width={w} height={h} rx='8' fill={main ? accent : 'none'} fillOpacity={main ? 0.12 : 1} stroke={main ? accent : edge} strokeWidth={main ? 2 : 1.25}/>;
  return <svg viewBox='0 0 760 656' role='img' aria-label='The app listens and inserts; the server recognises speech and knows the context' fontSize='13'>
    <defs><marker id='hld-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M0 0L10 5L0 10z' fill={edge}/></marker></defs>
    <text data-claude-text-id='title' x='24' y='28' fontSize='15' fontWeight='600' fill={ink}>Приложение слушает и вставляет; сервер распознаёт и знает контекст</text>
    <g data-claude-anchor='target'>{box(24, 48, 712, 56, false)}
      <text data-claude-text-id='target-name' x='36' y='72' fontWeight='600' fill={ink}>Целевое приложение</text>
      <text data-claude-text-id='target-1' x='36' y='88' fontSize='11.5' fill={quiet}>Claude Desktop, VS Code, терминал, Telegram: поле ввода с текстовым курсором.</text>
    </g>
    <g data-claude-anchor='app'>
      <rect x='24' y='144' width='712' height='176' rx='8' fill='none' stroke={edge} strokeWidth='1.25'/>
      <text data-claude-text-id='app-name' x='40' y='168' fontWeight='600' fill={ink}>Приложение Local Voice (macOS)</text>
    </g>
    <g data-claude-anchor='hotkey'>{box(40, 176, 332, 56, false)}
      <text data-claude-text-id='hotkey-name' x='52' y='200' fontWeight='600' fill={ink}>Клавиша и индикатор</text>
      <text data-claude-text-id='hotkey-1' x='52' y='216' fontSize='11.5' fill={quiet}>Старт и стоп; индикатор у текстового курсора.</text>
    </g>
    <g data-claude-anchor='insert'>{box(388, 176, 332, 56, false)}
      <text data-claude-text-id='insert-name' x='400' y='200' fontWeight='600' fill={ink}>Вставка (Accessibility)</text>
      <text data-claude-text-id='insert-1' x='400' y='216' fontSize='11.5' fill={quiet}>Текст — в поле, где стоял курсор при старте.</text>
    </g>
    <g data-claude-anchor='ui'>{box(40, 248, 332, 56, false)}
      <text data-claude-text-id='ui-name' x='52' y='272' fontWeight='600' fill={ink}>UI: строка меню, настройки, установщик</text>
      <text data-claude-text-id='ui-1' x='52' y='288' fontSize='11.5' fill={quiet}>Статус, модель, клавиша, установка моделей.</text>
    </g>
    <g data-claude-anchor='capture'>{box(388, 248, 332, 56, false)}
      <text data-claude-text-id='capture-name' x='400' y='272' fontWeight='600' fill={ink}>Захват звука</text>
      <text data-claude-text-id='capture-1' x='400' y='288' fontSize='11.5' fill={quiet}>Микрофон: 16 кГц, 16 бит, моно.</text>
    </g>
    <g data-claude-anchor='server'>
      <rect x='24' y='360' width='712' height='176' rx='8' fill={accent} fillOpacity='0.06' stroke={accent} strokeWidth='2'/>
      <text data-claude-text-id='server-name' x='40' y='384' fontWeight='600' fill={ink}>Сервер диктовки (бэкенд, launchd)</text>
    </g>
    <g data-claude-anchor='settings'>{box(40, 392, 332, 56, false)}
      <text data-claude-text-id='settings-name' x='52' y='416' fontWeight='600' fill={ink}>Настройки</text>
      <text data-claude-text-id='settings-1' x='52' y='432' fontSize='11.5' fill={quiet}>~/.local-voice/config.json; сервер следит за ним.</text>
    </g>
    <g data-claude-anchor='protocol'>{box(388, 392, 332, 56, false)}
      <text data-claude-text-id='protocol-name' x='400' y='416' fontWeight='600' fill={ink}>Протокол и запись</text>
      <text data-claude-text-id='protocol-1' x='400' y='432' fontSize='11.5' fill={quiet}>Одна запись за раз; файлы записи, метрики.</text>
    </g>
    <g data-claude-anchor='models'>{box(40, 464, 332, 56, false)}
      <text data-claude-text-id='models-name' x='52' y='488' fontWeight='600' fill={ink}>Модели и установка</text>
      <text data-claude-text-id='models-1' x='52' y='504' fontSize='11.5' fill={quiet}>Каталог, загрузка, агенты launchd.</text>
    </g>
    <g data-claude-anchor='adapters'>{box(388, 464, 332, 56, false)}
      <text data-claude-text-id='adapters-name' x='400' y='488' fontWeight='600' fill={ink}>Адаптеры контекста</text>
      <text data-claude-text-id='adapters-1' x='400' y='504' fontSize='11.5' fill={quiet}>Claude Code — первый: сессия и её ответы.</text>
    </g>
    <g data-claude-anchor='llama'>{box(24, 576, 340, 56, false)}
      <text data-claude-text-id='llama-name' x='36' y='600' fontWeight='600' fill={ink}>llama-server и Gemma 4 E4B</text>
      <text data-claude-text-id='llama-1' x='36' y='616' fontSize='11.5' fill={quiet}>Q8_0 или Q4_0; в памяти одна модель.</text>
    </g>
    <g data-claude-anchor='transcripts'>{box(396, 576, 340, 56, false)}
      <text data-claude-text-id='transcripts-name' x='408' y='600' fontWeight='600' fill={ink}>Транскрипты Claude Code</text>
      <text data-claude-text-id='transcripts-1' x='408' y='616' fontSize='11.5' fill={quiet}>~/.claude/projects/…/*.jsonl</text>
    </g>
    <g data-claude-anchor='connectors' fill='none' stroke={edge} strokeWidth='1.25'>
      <path d='M200 104V176' markerEnd='url(#hld-arrow)'/>
      <path d='M554 176V104' markerEnd='url(#hld-arrow)'/>
      <path d='M206 304V392' markerStart='url(#hld-arrow)' markerEnd='url(#hld-arrow)'/>
      <path d='M480 392V320' markerEnd='url(#hld-arrow)'/>
      <path d='M600 304V392' markerEnd='url(#hld-arrow)'/>
      <path d='M206 520V576' markerStart='url(#hld-arrow)' markerEnd='url(#hld-arrow)'/>
      <path d='M554 576V520' markerEnd='url(#hld-arrow)'/>
    </g>
    <text data-claude-text-id='e-hotkey' x='208' y='128' fontSize='11.5' fill={quiet}>клавиша, где курсор</text>
    <text data-claude-text-id='e-text-in' x='562' y='128' fontSize='11.5' fill={quiet}>текст</text>
    <text data-claude-text-id='e-settings' x='214' y='344' fontSize='11.5' fill={quiet}>настройки, установка</text>
    <text data-claude-text-id='e-text-status' x='392' y='344' fontSize='11.5' fill={quiet}>текст, статус</text>
    <text data-claude-text-id='e-audio' x='608' y='344' fontSize='11.5' fill={quiet}>звук</text>
    <text data-claude-text-id='e-llama' x='214' y='556' fontSize='11.5' fill={quiet}>запросы, агенты</text>
    <text data-claude-text-id='e-transcripts' x='562' y='556' fontSize='11.5' fill={quiet}>сессия, ответы Claude</text>
  </svg>;
};
