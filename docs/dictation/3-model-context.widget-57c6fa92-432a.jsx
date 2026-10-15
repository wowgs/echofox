export default () => {
  const ink = 'var(--cds-text-primary)', quiet = 'var(--cds-text-secondary)', edge = 'var(--cds-chart-axis)', bad = 'var(--cds-chart-status-critical)', tint = 'var(--cds-chart-reference-tint)';
  const cw = 340, c1 = 24, c3 = 396;
  const blk = (x, y, hh, kind) => <rect x={x + 12} y={y} width={cw - 24} height={hh} rx='8' fill={kind === 'bad' ? bad : kind === 'shared' ? tint : 'none'} fillOpacity={kind === 'bad' ? 0.12 : 1} stroke={kind === 'bad' ? bad : edge} strokeWidth={kind === 'bad' ? 2 : 1.25}/>;
  const col = x => <rect x={x} y='48' width={cw} height='352' rx='8' fill='none' stroke={edge} strokeWidth='1'/>;
  return <svg viewBox='0 0 760 424' role='img' aria-label='Piece 2 repeats piece 1 when the model sees its own previous answer' fontSize='13'>
    <text data-claude-text-id='title' x='24' y='28' fontSize='15' fontWeight='600' fill={ink}>Что видит модель, когда пишет кусок 2</text>
    <g data-claude-anchor='way-stacked'>{col(c1)}
      <text data-claude-text-id='stacked-name' x={c1 + 12} y='72' fontWeight='600' fill={ink}>Было: куски поверх</text>
      {blk(c1, 88, 48, 'plain')}
      <text data-claude-text-id='stacked-text' x={c1 + 24} y='110' fontSize='11.5' fill={ink}>История чата + промпт</text>
      <text data-claude-text-id='stacked-text-2' x={c1 + 24} y='126' fontSize='11.5' fill={quiet}>посчитано один раз</text>
      {blk(c1, 144, 32, 'plain')}
      <text data-claude-text-id='stacked-a1' x={c1 + 24} y='164' fontSize='11.5' fill={ink}>Звук куска 1</text>
      {blk(c1, 184, 48, 'bad')}
      <text data-claude-text-id='stacked-r1' x={c1 + 24} y='206' fontSize='11.5' fontWeight='600' fill={ink}>Ответ модели на кусок 1</text>
      <text data-claude-text-id='stacked-r1-2' x={c1 + 24} y='222' fontSize='11.5' fill={quiet}>модель его видит</text>
      {blk(c1, 240, 32, 'plain')}
      <text data-claude-text-id='stacked-a2' x={c1 + 24} y='260' fontSize='11.5' fill={ink}>Звук куска 2</text>
      <text data-claude-text-id='stacked-out' x={c1 + 12} y='304' fontSize='11.5' fontWeight='600' fill={ink}>Результат:</text>
      <text data-claude-text-id='stacked-out-1' x={c1 + 12} y='320' fontSize='11.5' fill={quiet}>часто повтор ответа 1,</text>
      <text data-claude-text-id='stacked-out-2' x={c1 + 12} y='336' fontSize='11.5' fill={quiet}>потом текст куска 2</text>
      <text data-claude-text-id='stacked-out-3' x={c1 + 12} y='368' fontSize='11.5' fill={quiet}>было до 14 октября</text>
    </g>
    <g data-claude-anchor='way-fresh'>{col(c3)}
      <text data-claude-text-id='fresh-name' x={c3 + 12} y='72' fontWeight='600' fill={ink}>Сейчас: отдельный запрос на кусок</text>
      {blk(c3, 88, 48, 'shared')}
      <text data-claude-text-id='fresh-text' x={c3 + 24} y='110' fontSize='11.5' fill={ink}>История чата + промпт</text>
      <text data-claude-text-id='fresh-text-2' x={c3 + 24} y='126' fontSize='11.5' fill={quiet}>один на все куски, в кэше llama-server</text>
      {blk(c3, 144, 32, 'plain')}
      <text data-claude-text-id='fresh-a2' x={c3 + 24} y='164' fontSize='11.5' fill={ink}>Звук куска 2</text>
      <text data-claude-text-id='fresh-out' x={c3 + 12} y='304' fontSize='11.5' fontWeight='600' fill={ink}>Результат:</text>
      <text data-claude-text-id='fresh-out-1' x={c3 + 12} y='320' fontSize='11.5' fill={quiet}>прошлых ответов в запросе нет</text>
      <text data-claude-text-id='fresh-out-3' x={c3 + 12} y='368' fontSize='11.5' fill={quiet}>используется сейчас</text>
    </g>
  </svg>;
};
