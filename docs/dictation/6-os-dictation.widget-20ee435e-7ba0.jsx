export default () => {
  const ink = 'var(--cds-text-primary)', quiet = 'var(--cds-text-secondary)', edge = 'var(--cds-chart-axis)', accent = 'var(--cds-chart-categorical-1)';
  const box = (x, y, w, h, main) => <rect x={x} y={y} width={w} height={h} rx='8' fill={main ? accent : 'none'} fillOpacity={main ? 0.12 : 1} stroke={main ? accent : edge} strokeWidth={main ? 2 : 1.25}/>;
  return <svg viewBox='0 0 760 472' role='img' aria-label='A hotkey starts our recording; the text from our model goes where the cursor is, in any app' fontSize='13'>
    <defs><marker id='hk-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M0 0L10 5L0 10z' fill={edge}/></marker></defs>
    <text data-claude-text-id='title' x='24' y='28' fontSize='15' fontWeight='600' fill={ink}>Горячая клавиша: звук идёт к нашей модели, текст — туда, где курсор</text>
    <g data-claude-anchor='any-app'>{box(24, 48, 712, 72, false)}
      <text data-claude-text-id='app-any-name' x='36' y='72' fontWeight='600' fill={ink}>Любое приложение с полем ввода</text>
      <text data-claude-text-id='app-any-1' x='36' y='88' fontSize='11.5' fill={quiet}>Claude Desktop, VS Code, терминал. Само приложение не меняется.</text>
      <text data-claude-text-id='app-any-2' x='36' y='104' fontSize='11.5' fill={quiet}>Его диктовка не участвует.</text>
    </g>
    <g data-claude-anchor='app'>
      <rect x='24' y='160' width='712' height='176' rx='8' fill='none' stroke={edge} strokeWidth='1.25'/>
      <text data-claude-text-id='app-name' x='40' y='184' fontWeight='600' fill={ink}>Наше приложение в строке меню (macOS)</text>
      <text data-claude-text-id='app-menu' x='720' y='184' textAnchor='end' fontSize='11.5' fill={quiet}>меню: модель, язык, config.json, статус</text>
    </g>
    <g data-claude-anchor='hotkey'>{box(40, 192, 332, 56, false)}
      <text data-claude-text-id='hotkey-name' x='52' y='216' fontWeight='600' fill={ink}>Горячая клавиша</text>
      <text data-claude-text-id='hotkey-1' x='52' y='232' fontSize='11.5' fill={quiet}>Старт и стоп записи; запоминает поле с курсором.</text>
    </g>
    <g data-claude-anchor='insert'>{box(388, 192, 332, 56, false)}
      <text data-claude-text-id='insert-name' x='400' y='216' fontWeight='600' fill={ink}>Вставка текста (Accessibility)</text>
      <text data-claude-text-id='insert-1' x='400' y='232' fontSize='11.5' fill={quiet}>В запомненное поле, на место курсора.</text>
    </g>
    <g data-claude-anchor='capture'>{box(40, 264, 332, 56, false)}
      <text data-claude-text-id='capture-name' x='52' y='288' fontWeight='600' fill={ink}>Захват звука</text>
      <text data-claude-text-id='capture-1' x='52' y='304' fontSize='11.5' fill={quiet}>Микрофон: 16 кГц, 16 бит, моно.</text>
    </g>
    <g data-claude-anchor='client'>{box(388, 264, 332, 56, false)}
      <text data-claude-text-id='client-name' x='400' y='288' fontWeight='600' fill={ink}>Клиент сервера</text>
      <text data-claude-text-id='client-1' x='400' y='304' fontSize='11.5' fill={quiet}>Звук на сервер, текст обратно.</text>
    </g>
    <g data-claude-anchor='server'>{box(388, 376, 348, 72, true)}
      <text data-claude-text-id='server-name' x='400' y='400' fontWeight='600' fill={ink}>gemma_voice.py → llama-server</text>
      <text data-claude-text-id='server-1' x='400' y='416' fontSize='11.5' fill={ink}>Gemma 4 E4B через llama.cpp.</text>
      <text data-claude-text-id='server-2' x='400' y='432' fontSize='11.5' fill={ink}>Протокол сервера не меняется.</text>
    </g>
    <g data-claude-anchor='connectors' fill='none' stroke={edge} strokeWidth='1.25'>
      <path d='M200 120V192' markerEnd='url(#hk-arrow)'/>
      <path d='M440 192V120' markerEnd='url(#hk-arrow)'/>
      <path d='M206 248V264' markerEnd='url(#hk-arrow)'/>
      <path d='M372 292H388' markerEnd='url(#hk-arrow)'/>
      <path d='M554 264V248' markerEnd='url(#hk-arrow)'/>
      <path d='M520 320V376' markerEnd='url(#hk-arrow)'/>
      <path d='M600 376V320' markerEnd='url(#hk-arrow)'/>
    </g>
    <text data-claude-text-id='edge-press' x='208' y='146' fontSize='11.5' fill={quiet}>ты жмёшь клавишу, курсор в поле</text>
    <text data-claude-text-id='edge-text-in' x='448' y='146' fontSize='11.5' fill={quiet}>текст в поле</text>
    <text data-claude-text-id='edge-audio' x='512' y='356' textAnchor='end' fontSize='11.5' fill={quiet}>звук</text>
    <text data-claude-text-id='edge-text' x='608' y='356' fontSize='11.5' fill={quiet}>текст</text>
  </svg>;
};
