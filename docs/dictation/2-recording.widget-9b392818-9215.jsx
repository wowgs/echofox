export default () => {
  const ink = 'var(--cds-text-primary)', quiet = 'var(--cds-text-secondary)', edge = 'var(--cds-chart-axis)', warn = 'var(--cds-chart-status-warning)';
  const bx = 128, bw = 608, h = 56;
  const box = (y, w8) => <rect x={bx} y={y} width={bw} height={h} rx='8' fill={w8 ? warn : 'none'} fillOpacity={w8 ? 0.12 : 1} stroke={w8 ? warn : edge} strokeWidth={w8 ? 2 : 1.25}/>;
  return <svg viewBox='0 0 760 552' role='img' aria-label='One recording: the audio builds up while you speak; after the stop each piece is a request of its own' fontSize='13'>
    <defs><marker id='tl-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M0 0L10 5L0 10z' fill={edge}/></marker></defs>
    <text data-claude-text-id='title' x='24' y='28' fontSize='15' fontWeight='600' fill={ink}>Пока ты говоришь, звук копится; после стопа каждый кусок — отдельный запрос</text>
    <g data-claude-anchor='connectors' fill='none' stroke={edge} strokeWidth='1.25'>
      <path d='M432 104V120' markerEnd='url(#tl-arrow)'/>
      <path d='M432 176V192' markerEnd='url(#tl-arrow)'/>
      <path d='M432 248V264' markerEnd='url(#tl-arrow)'/>
      <path d='M432 320V336' markerEnd='url(#tl-arrow)'/>
      <path d='M432 392V408' markerEnd='url(#tl-arrow)'/>
      <path d='M432 464V480' markerEnd='url(#tl-arrow)'/>
    </g>
    <g data-claude-anchor='step-start'>{box(48, false)}
      <text data-claude-text-id='t-start' x='24' y='72' fontSize='11.5' fill={quiet}>0 с</text>
      <text data-claude-text-id='start-name' x={bx + 12} y='72' fontWeight='600' fill={ink}>Старт записи: start</text>
      <text data-claude-text-id='start-1' x={bx + 12} y='88' fontSize='11.5' fill={quiet}>Имя модели, язык, сессии или приложение; сервер пишет mic.wav; звук идёт сразу.</text>
    </g>
    <g data-claude-anchor='step-context'>{box(120, false)}
      <text data-claude-text-id='t-context' x='24' y='144' fontSize='11.5' fill={quiet}>пока говоришь</text>
      <text data-claude-text-id='context-name' x={bx + 12} y='144' fontWeight='600' fill={ink}>Сервер читает историю чата</text>
      <text data-claude-text-id='context-1' x={bx + 12} y='160' fontSize='11.5' fill={quiet}>Мои итоговые ответы и английские термины из JSONL сессии.</text>
    </g>
    <g data-claude-anchor='step-prefill'>{box(192, false)}
      <text data-claude-text-id='t-prefill' x='24' y='216' fontSize='11.5' fill={quiet}>пока говоришь</text>
      <text data-claude-text-id='prefill-name' x={bx + 12} y='216' fontWeight='600' fill={ink}>Сервер собирает текст перед звуком</text>
      <text data-claude-text-id='prefill-1' x={bx + 12} y='232' fontSize='11.5' fill={quiet}>История в бюджете токенов, термины, промпт; токены считает llama-server.</text>
    </g>
    <g data-claude-anchor='step-piece1'>{box(264, false)}
      <text data-claude-text-id='t-piece1' x='24' y='288' fontSize='11.5' fill={quiet}>пока говоришь</text>
      <text data-claude-text-id='piece1-name' x={bx + 12} y='288' fontWeight='600' fill={ink}>Звук копится, сервер считает громкость</text>
      <text data-claude-text-id='piece1-1' x={bx + 12} y='304' fontSize='11.5' fill={quiet}>Речь, фон, пик, перегруз и цифровую тишину — для audio.json.</text>
    </g>
    <g data-claude-anchor='step-pieces'>{box(336, false)}
      <text data-claude-text-id='t-pieces' x='24' y='360' fontSize='11.5' fill={quiet}>после стопа</text>
      <text data-claude-text-id='pieces-name' x={bx + 12} y='360' fontWeight='600' fill={ink}>Нарезка на равные куски около 20 с</text>
      <text data-claude-text-id='pieces-1' x={bx + 12} y='376' fontSize='11.5' fill={quiet}>Не длиннее 30 с, разрез в самой тихой паузе ±3 с от точки деления.</text>
    </g>
    <g data-claude-anchor='step-stop'>{box(408, false)}
      <text data-claude-text-id='t-stop' x='24' y='432' fontSize='11.5' fill={quiet}>по кускам</text>
      <text data-claude-text-id='stop-name' x={bx + 12} y='432' fontWeight='600' fill={ink}>Каждый кусок — отдельный запрос к llama-server</text>
      <text data-claude-text-id='stop-1' x={bx + 12} y='448' fontSize='11.5' fill={quiet}>Текст перед звуком и звук куска; прошлых ответов модель не видит.</text>
    </g>
    <g data-claude-anchor='step-done'>{box(480, false)}
      <text data-claude-text-id='t-done' x='24' y='504' fontSize='11.5' fill={quiet}>по кускам</text>
      <text data-claude-text-id='done-name' x={bx + 12} y='504' fontWeight='600' fill={ink}>Тексты по порядку, затем done</text>
      <text data-claude-text-id='done-1' x={bx + 12} y='520' fontSize='11.5' fill={quiet}>Сервер дописывает adapter.json.</text>
    </g>
  </svg>;
};
