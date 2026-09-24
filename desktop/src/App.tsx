import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { listen } from '@tauri-apps/api/event';
import { open } from '@tauri-apps/plugin-dialog';
import { Activity, AlertCircle, AppWindow, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpRight, AudioLines, BookOpen, Calculator, Check, ChevronRight, Clock3, Cpu, FileText, FolderOpen, Grid3X3, Keyboard, LayoutDashboard, Maximize2, Mic, MicOff, Minimize2, Monitor, MousePointer2, NotebookPen, Plus, Power, RefreshCw, Search, Settings2, ShieldCheck, Square, X } from 'lucide-react';
import { isDesktop, request, invoke } from './bridge';
import { defaults, type ActionResult, type FileHit, type Message, type Settings, type Snapshot, type WindowInfo, type TaskStatus, type ProviderStatus } from './types';
import { guide } from './guide';
import SettingsPage from './SettingsPage';
import MissionControl, { type ResponseTiming } from './MissionControl';

type Page = 'overview' | 'assistant' | 'control' | 'files' | 'memory' | 'settings';
const navigation = [
  { id: 'overview' as Page, title: 'Mission control', icon: Activity },
  { id: 'assistant' as Page, title: 'Assistant', icon: LayoutDashboard },
  { id: 'control' as Page, title: 'Desktop control', icon: Monitor },
  { id: 'files' as Page, title: 'Files & folders', icon: FolderOpen },
  { id: 'memory' as Page, title: 'Notes & reminders', icon: NotebookPen },
  { id: 'settings' as Page, title: 'Settings', icon: Settings2 },
];
function Logo({ small = false }: { small?: boolean }) {
  return <div className={'logo ' + (small ? 'small' : '')} aria-hidden="true"><span/><span/><span/><span/></div>;
}
function Pill({ children, active = false }: { children: ReactNode; active?: boolean }) {
  return <span className={'pill ' + (active ? 'green' : '')}><i/>{children}</span>;
}
export default function App() {
  const [page, setPage] = useState<Page>('overview');
  const [snapshot, setSnapshot] = useState<Snapshot>(defaults);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState('');
  const [notification, setNotification] = useState('');
  const [text, setText] = useState('');
  const [replyProgress, setReplyProgress] = useState('');
  const [sessionTasks, setSessionTasks] = useState<TaskStatus[]>([]);
  const [responseTiming, setResponseTiming] = useState<ResponseTiming | null>(null);
  const [result, setResult] = useState<ActionResult | null>(null);
  const [level, setLevel] = useState(0);
  const [cpu, setCpu] = useState(0);
  const [setup, setSetup] = useState({ message: '', running: false });
  const [guideQuery, setGuideQuery] = useState('');
  const [guideCategory, setGuideCategory] = useState('All');
  const [fileQuery, setFileQuery] = useState('');
  const [fileKind, setFileKind] = useState('');
  const [files, setFiles] = useState<FileHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [windows, setWindows] = useState<WindowInfo[]>([]);
  const [note, setNote] = useState('');
  const [reminder, setReminder] = useState('');
  const [aliasFile, setAliasFile] = useState<FileHit | null>(null);
  const [aliasName, setAliasName] = useState('');
  const connecting = useRef(false);
  const conversationEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const fileSearchId = useRef(0);
  const patch = useCallback((value: Partial<Snapshot>) => setSnapshot(s => ({ ...s, ...value })), []);
  const run = useCallback(async (work: () => Promise<unknown>) => {
    try { await work(); } catch (e) { setError(String(e).replace(/^Error: /, '')); }
  }, []);
  const connect = useCallback(async () => {
    if (connecting.current || !isDesktop) return;
    connecting.current = true;
    try { const state = await request<Snapshot>('connect'); setSnapshot(state); setConnected(true); setError(''); }
    catch (e) { setConnected(false); setError(String(e)); }
    finally { connecting.current = false; }
  }, []);
  useEffect(() => {
    if (!isDesktop) { patch({ status: 'Desktop app preview' }); return; }
    let disposed = false;
    let cleanup: (() => void) | undefined;
    let lastLevel = 0;
    void listen<{ event: string; data: unknown }>('engine-event', event => {
      const { event: kind, data } = event.payload;
      if (kind === 'ready') { setReplyProgress(''); setSessionTasks([]); setResponseTiming(null); void connect(); }
      if (kind === 'reply_progress') setReplyProgress((data as { content: string }).content);
      if (kind === 'task') {
        const task = data as TaskStatus;
        patch({ current_task: task });
        setSessionTasks(previous => [...previous.filter(item => item.id !== task.id), task].slice(-20));
      }
      if (kind === 'response_timing') setResponseTiming(data as ResponseTiming);
      if (kind === 'provider') patch({ provider: data as ProviderStatus });
      if (kind === 'notification') setNotification(String(data));
      if (kind === 'status') patch({ status: String(data) });
      if (kind === 'listening') { patch({ listening: Boolean(data) }); if (!data) setLevel(0); }
      if (kind === 'busy') { patch({ busy: Boolean(data) }); if (!data) setReplyProgress(''); }
      if (kind === 'level' && performance.now() - lastLevel > 70) { setLevel(Number(data)); lastLevel = performance.now(); }
      if (kind === 'message') { setReplyProgress(''); setSnapshot(s => ({ ...s, history: [...s.history, data as Message].slice(-100) })); }
      if (kind === 'result') setResult(data as ActionResult);
      if (kind === 'index') patch(data as Partial<Snapshot>);
      if (kind === 'activity') patch(data as Partial<Snapshot>);
      if (kind === 'metrics') { const metrics = data as { memory_percent: number; speaking: boolean; cpu_percent: number }; patch(metrics); setCpu(metrics.cpu_percent); }
      if (kind === 'error') setError(String(data));
      if (kind === 'disconnected') { setReplyProgress(''); setConnected(false); patch({ listening: false, busy: false, status: 'Engine disconnected' }); setError(String(data)); }
      if (kind === 'setup') {
        const progress = data as { message: string; running: boolean };
        setSetup(progress);
        if (!progress.running) void request<Snapshot>('snapshot').then(setSnapshot).catch(e => setError(String(e)));
      }
    }).then(unlisten => { if (disposed) unlisten(); else { cleanup = unlisten; void connect(); } }).catch(e => setError(String(e)));
    return () => { disposed = true; cleanup?.(); };
  }, [connect, patch]);
  useEffect(() => { conversationEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [snapshot.history, result, replyProgress]);
  useEffect(() => { if (page === 'control' && connected) void run(async () => setWindows(await request<WindowInfo[]>('windows'))); }, [page, connected, run]);
  const execute = (command: string) => {
    if (!command.trim()) return;
    setResult(null);
    void run(async () => {
      const accepted = await request<{ accepted: boolean }>('command', { text: command });
      if (!accepted.accepted) throw new Error('A command is already running. Use Stop before starting another.');
      setText('');
    });
  };
  const prefill = (command: string) => { setPage('assistant'); setText(command); setTimeout(() => input.current?.focus(), 0); };
  const refresh = () => void run(async () => setSnapshot(await request<Snapshot>('snapshot')));
  const toggleVoice = () => void run(async () => { await request('listen', { enabled: !snapshot.listening }); });
  const searchFiles = () => {
    if (!fileQuery.trim()) return;
    const searchId = ++fileSearchId.current;
    setSearching(true);
    void run(async () => {
      try { const found = await request<FileHit[]>('files', { query: fileQuery, kind: fileKind }); if (searchId === fileSearchId.current) { setFiles(found); setSearched(true); } }
      finally { if (searchId === fileSearchId.current) setSearching(false); }
    });
  };
  const saveSettings = async (values: Partial<Settings>) => {
    const previous = snapshot.settings;
    const saved = await request<Settings>('settings', { values });
    if (values.start_with_windows !== undefined && values.start_with_windows !== previous.start_with_windows) {
      try { await invoke('set_autostart', { enabled: values.start_with_windows }); }
      catch (e) { await request('settings', { values: { start_with_windows: previous.start_with_windows } }); throw e; }
    }
    patch({ settings: saved });
  };
  const addSearchFolder = () => void run(async () => {
    const folder = await open({ directory: true, multiple: false, title: 'Add a folder to Jarvis' });
    if (typeof folder === 'string') await saveSettings({ search_roots: [...new Set([...snapshot.settings.search_roots, folder])] });
  });
  const statusWord = !connected ? 'OFFLINE' : snapshot.busy ? 'WORKING' : snapshot.speaking ? 'SPEAKING' : snapshot.listening ? 'LISTENING' : 'STANDBY';
  const canCommand = connected && !snapshot.busy;
  const visibleGuide = guide.filter(item => (guideCategory === 'All' || item.category === guideCategory) && `${item.title} ${item.command} ${item.detail}`.toLowerCase().includes(guideQuery.toLowerCase()));
  const pageTitle = navigation.find(item => item.id === page)!.title;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><Logo/><div><strong>jarvis<span>®</span></strong><small>YOUR PERSONAL ASSISTANT</small></div></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{navigation.map(item => <button key={item.id} className={'nav-item ' + (page === item.id ? 'selected' : '')} onClick={() => setPage(item.id)}><item.icon size={19}/>{item.title}{page === item.id && <i/>}</button>)}</nav>
      <div className="sidebar-bottom">
        <div className="local-card"><ShieldCheck size={21}/><strong>Made for your privacy</strong><p>Your voice, conversations, and files stay on this computer.</p><span><i/>{snapshot.provider.online ? "Online AI active" : "Local AI"}</span></div>
        <button className="guide-link" onClick={() => { setPage('control'); setGuideCategory('All'); }}><BookOpen size={17}/> Voice command guide <ArrowUpRight size={14}/></button>
        <div className="profile"><div className="avatar">{snapshot.settings.user_name.slice(0, 1).toUpperCase()}</div><div><strong>{snapshot.settings.user_name === 'You' ? 'Your workspace' : snapshot.settings.user_name}</strong><small>Personal · On this device</small></div><button aria-label="Open settings" className="icon-button" onClick={() => setPage('settings')}><Settings2 size={16}/></button></div>
      </div>
    </aside>
    <section className="main-shell">
      <header className="topbar"><div><span>Workspace</span><ChevronRight size={13}/><strong>{pageTitle}</strong></div><div><span className="connection"><i className={connected ? 'online' : ''}/>{connected ? 'Local engine connected' : isDesktop ? 'Connecting to engine' : 'Interface preview'}</span><span className="version">DESKTOP 1.0</span></div></header>
      {!isDesktop && <div className="preview-banner"><Monitor size={16}/> Interface preview. Open the Jarvis desktop app to use voice and control this PC.</div>}
      {isDesktop && !connected && <div className="connection-banner"><AlertCircle size={17}/><span>Waiting for your local assistant.</span><button onClick={() => void run(async () => { await invoke('restart_engine'); await connect(); })}>Reconnect</button></div>}
      {connected && <div className="connection-banner"><ShieldCheck size={16}/><span>{snapshot.security.description}</span><small>{snapshot.current_task ? `${snapshot.current_task.steps.at(-1)?.tool || "Task"} · ${snapshot.current_task.state}` : "No active task"}</small></div>}
      <main className={'page-content page-' + page}>
        {page === 'overview' && <MissionControl snapshot={snapshot} connected={connected} cpu={cpu} tasks={sessionTasks} timing={responseTiming} talk={()=>setPage('assistant')} reminders={()=>setPage('memory')} activate={toggleVoice} stop={()=>void run(async()=>{await request('emergency');})} command={execute}/>}
        {page === 'assistant' && <>
          <div className="page-heading"><div><span className="eyebrow">A LITTLE LESS CLICKING. A LOT MORE DOING.</span><h1>Your desktop. Just say the word.</h1><p>Open an app, find a file, or get something done. I’m here to help.</p></div><Pill active={connected}>Runs on your PC</Pill></div>
          <section className={'voice-hero ' + (snapshot.listening ? 'active' : '')} aria-label="Voice activation">
            <div className="hero-copy"><div className="live-status"><i className={snapshot.listening ? 'pulse' : ''}/>{statusWord}</div><h2>{snapshot.listening ? 'All ears. All yours.' : snapshot.busy ? 'Consider it in progress.' : 'Your next move, hands free.'}</h2><p>{snapshot.listening ? <>Say <b>“{snapshot.settings.wake_word}, open notepad”</b><br/>and let’s get to work.</> : <>Activate Jarvis and speak naturally.<br/>Your commands are processed right here.</>}</p><div className="hero-actions"><button className="button primary" disabled={!connected} onClick={toggleVoice}>{snapshot.listening ? <MicOff size={17}/> : <Mic size={17}/>} {snapshot.listening ? 'Pause listening' : 'Activate Jarvis'}</button><button className="button quiet" disabled={!connected || snapshot.busy} onClick={() => void run(async () => { await request('listen', { enabled: true, once: true }); })}>Listen once <span className="keycap">⌃ ⌥ J</span></button></div></div>
            <div className={'voice-orb ' + (snapshot.busy ? 'thinking' : '')} aria-hidden="true"><div className="orb-ring r1"/><div className="orb-ring r2"/><div className="orb-ring r3"/><div className="orb-core"><AudioLines size={42} strokeWidth={1.1}/></div><span className="orb-dot d1"/><span className="orb-dot d2"/><div className="orb-caption">J A R V I S <span>LOCAL INTELLIGENCE</span></div></div>
            <div className="hero-foot"><span><span className="audio-bars">{[.3,.65,.95,.5,.8,.4,.7].map((n,i)=><i key={i} style={{height: 3 + level*n*.2}}/>)}</span>{snapshot.status}</span><button disabled={!connected} onClick={() => void run(async () => { await request('emergency'); })}><Square size={12}/> Pause & stop <kbd>Ctrl Alt Esc</kbd></button></div>
          </section>
          <div className="assistant-columns"><section className="conversation panel"><div className="section-heading"><h3><AudioLines size={17}/> Conversation</h3><span>PRIVATE & LOCAL</span></div><div className="messages" role="log" aria-label="Conversation" aria-live="polite">
            {snapshot.history.length === 0 && <div className="welcome-message"><Logo small/><h3>A helping hand, one command away.</h3><p>Ask me to open an app, find a document, set a reminder, or explain something.</p><div className="suggestions">{['What can you do?', 'Open downloads', 'What time is it?'].map(command => <button key={command} onClick={() => prefill(command)}>{command}<ArrowUpRight size={13}/></button>)}</div></div>}
            {snapshot.history.map((message, i) => <div key={i} className={'message ' + (message.role === 'user' ? 'from-user' : 'from-jarvis')}><div className="message-avatar">{message.role === 'user' ? snapshot.settings.user_name.slice(0,1).toUpperCase() : <Logo small/>}</div><div><span>{message.role === 'user' ? 'YOU' : 'JARVIS'}</span><p>{message.content}</p></div></div>)}
            {result?.data?.choices && <div className="choices">{result.data.choices.map((choice,i)=><button disabled={!canCommand} key={i} onClick={() => execute(`choose ${i+1}`)}><span>{i+1}</span><div>{choice.name}<small>{choice.path || ''}</small></div><ArrowUpRight size={15}/></button>)}</div>}
            {result?.data?.confirmation && <div className="confirmation"><AlertCircle size={18}/><div>Confirm this action?<small>Say yes or no within 30 seconds.</small></div><button className="button primary compact" disabled={!canCommand} onClick={()=>execute('yes')}>Confirm</button><button className="button compact" disabled={!canCommand} onClick={()=>execute('no')}>Cancel</button></div>}
            {replyProgress && <div className="message from-jarvis" aria-label="Jarvis reply in progress"><div className="message-avatar"><Logo small/></div><div><span>JARVIS · REPLYING</span><p>{replyProgress}</p></div></div>}
            {snapshot.busy && !replyProgress && <div className="working"><i/><i/><i/><span>Working on your command…</span></div>}<div ref={conversationEnd}/></div>
            <form className="composer" onSubmit={e=>{e.preventDefault();execute(text);}}><input ref={input} aria-label="Ask Jarvis" placeholder="Type a command or ask anything…" value={text} onChange={e=>setText(e.target.value)}/><button type="button" className="icon-button" aria-label="Listen to one command" disabled={!connected || snapshot.busy} onClick={()=>void run(async()=>{await request('listen',{enabled:true,once:true});})}><Mic size={18}/></button><button className="send-button" aria-label="Send command" disabled={!canCommand || !text.trim()}><ArrowUp size={18}/></button></form><div className="composer-caption"><ShieldCheck size={12}/> Only you and your computer.<span>Enter to send</span></div>
          </section><aside className="quick-column"><section className="panel quick-apps"><div className="section-heading"><h3>Quick launch</h3><AppWindow size={16}/></div><div className="app-grid">{[{name:'Notepad',command:'open notepad',icon:FileText},{name:'Files',command:'open downloads',icon:FolderOpen},{name:'Calculator',command:'open calculator',icon:Calculator},{name:'Settings',command:'open windows settings',icon:Settings2}].map(app=><button disabled={!canCommand} key={app.name} onClick={()=>execute(app.command)}><app.icon size={22}/><span>{app.name}</span></button>)}</div></section><section className="panel try-panel"><span className="eyebrow">TRY SAYING</span><h3>A few words.<br/>A little more done.</h3>{['Find PDF invoice','Remind me in 10 minutes to stretch','Show grid'].map(command=><button key={command} onClick={()=>prefill(command)}>“{command}”<ArrowUpRight size={14}/></button>)}<button className="text-link" onClick={()=>setPage('control')}>Explore all commands <ArrowRight size={14}/></button></section><div className="device-status"><span><Cpu size={15}/> ON THIS DEVICE</span><div><span>Voice recognition</span><b>{snapshot.speech_ready?'Ready':'Needs setup'}</b></div><div><span>Local intelligence</span><b>{snapshot.chat_ready?'Ready':'Needs setup'}</b></div>{connected&&<div><span>CPU / memory</span><b>{Math.round(cpu)}% / {Math.round(snapshot.memory_percent)}%</b></div>}{connected&&(!snapshot.speech_ready||!snapshot.chat_ready)&&<button className="text-link" onClick={()=>setPage('settings')}>Prepare local models <ArrowRight size={12}/></button>}</div></aside></div>
        </>}
        {page === 'control' && <>
          <div className="page-heading"><div><span className="eyebrow">YOUR VOICE. YOUR WORKSPACE.</span><h1>Take the controls.</h1><p>Work across your desktop with a few familiar words.</p></div><button className="button" disabled={!canCommand} onClick={()=>execute('show grid')}><Grid3X3 size={17}/> Show mouse grid</button></div>
          <div className="control-summary"><div className="panel control-tip"><MousePointer2/><div><h3>Point. Speak. Done.</h3><p>Say “show grid”, then “zoom five” to narrow the target. Say “click three” to click it.</p></div></div><div className="panel control-tip"><Keyboard/><div><h3>Your shortcuts, spoken.</h3><p>Say “press control S”, “copy”, “paste”, or “type” followed by your text.</p></div></div></div>
          <section className="panel windows-panel"><div className="section-heading"><h3><AppWindow size={17}/> Open windows <span className="count">{windows.length}</span></h3><button className="text-link" disabled={!connected} onClick={()=>void run(async()=>setWindows(await request<WindowInfo[]>('windows')))}><RefreshCw size={14}/> Refresh</button></div>{windows.length===0?<div className="inline-empty">Your open application windows appear here when Jarvis is connected.</div>:<div className="window-list">{windows.slice(0,12).map(window=><div className="window-row" key={window.hwnd}><AppWindow size={18}/><div><strong>{window.name}</strong><small>{window.process}</small></div><button disabled={!canCommand} className="button compact" onClick={()=>execute(`focus ${window.name}`)}>Focus</button><button disabled={!canCommand} aria-label={`Minimize ${window.name}`} className="icon-button" onClick={()=>execute(`minimize ${window.name}`)}><Minimize2 size={15}/></button><button disabled={!canCommand} aria-label={`Maximize ${window.name}`} className="icon-button" onClick={()=>execute(`maximize ${window.name}`)}><Maximize2 size={15}/></button></div>)}</div>}</section>
          <div className="guide-heading"><h2>Voice command library</h2><div className="search-box"><Search size={16}/><input value={guideQuery} onChange={e=>setGuideQuery(e.target.value)} placeholder="Find a command…" aria-label="Search commands"/></div></div><div className="tabs">{['All',...new Set(guide.map(g=>g.category))].map(category=><button key={category} className={guideCategory===category?'active':''} onClick={()=>setGuideCategory(category)}>{category}</button>)}</div><div className="command-grid">{visibleGuide.map(item=><button className="command-card" key={item.title} onClick={()=>prefill(item.command)}><span>{item.category}<ArrowUpRight size={14}/></span><h3>{item.title}</h3><code>“{item.command}”</code><p>{item.detail}</p></button>)}</div>{!visibleGuide.length&&<div className="empty-state"><Search/><h3>No matching commands</h3><p>Try a word such as file, mouse, or voice.</p></div>}
        </>}
        {page === 'files' && <>
          <div className="page-heading"><div><span className="eyebrow">RIGHT WHERE YOU LEFT IT.</span><h1>A place for everything.</h1><p>Find files on your computer and give your favorites a name you can say.</p></div><button className="button" disabled={!connected} onClick={addSearchFolder}><Plus size={17}/> Add folder</button></div>
          <section className="panel file-panel"><form className="file-search" onSubmit={e=>{e.preventDefault();searchFiles();}}><div className="search-box"><Search size={18}/><input aria-label="Search local files" value={fileQuery} onChange={e=>setFileQuery(e.target.value)} placeholder="Search a filename or paste a complete path…"/></div><select aria-label="File type" value={fileKind} onChange={e=>setFileKind(e.target.value)}>{[['','All types'],['folder','Folders'],['pdf','PDFs'],['document','Documents'],['image','Images'],['spreadsheet','Spreadsheets'],['video','Videos']].map(([key,title])=><option value={key} key={key}>{title}</option>)}</select><button className="button primary" disabled={!connected||searching||!fileQuery.trim()}>{searching?'Searching…':'Search files'}</button></form><div className="file-index"><span><i/>{snapshot.indexing?'Indexing your folders…':`${snapshot.index_count.toLocaleString()} files and folders indexed`}</span><button className="text-link" disabled={!connected||snapshot.indexing} onClick={()=>void run(async()=>{await request('index');})}><RefreshCw size={13}/> Refresh index</button></div>
          {files.length>0?<div className="file-list">{files.map(file=><div className="file-row" key={file.path}><span className="file-icon">{file.is_dir?<FolderOpen size={22}/>:<FileText size={22}/>}</span><div><strong>{file.name}</strong><small title={file.path}>{file.path}</small></div><button disabled={!connected} className="button compact" onClick={()=>{setAliasFile(file);setAliasName('');}}>Voice name</button><button disabled={!canCommand} className="button compact" onClick={()=>execute(`open file ${file.path}`)}>Open <ArrowUpRight size={13}/></button></div>)}</div>:<div className="empty-state"><FolderOpen size={38}/><h3>{searched?'No files found.':'Your files, a word away.'}</h3><p>{searched?'Try another name, refresh the index, or add the folder containing your file.':'Search for a document, folder, photo, or spreadsheet. File contents stay untouched.'}</p></div>}</section><div className="file-footer"><Mic size={17}/><span>Try <b>“Jarvis, find PDF invoice”</b>, then say <b>“open the first one.”</b></span></div>
        </>}
        {page === 'memory' && <>
          <div className="page-heading"><div><span className="eyebrow">A LITTLE SPACE TO REMEMBER.</span><h1>Off your mind. On your desktop.</h1><p>Small notes and timely reminders, saved privately on this computer.</p></div><button className="button" disabled={!connected} onClick={refresh}><RefreshCw size={15}/> Refresh</button></div>
          <div className="memory-grid"><section className="panel"><div className="section-heading"><h3><NotebookPen size={18}/> Your notes</h3><span>{snapshot.notes.length} SAVED</span></div><form className="memory-form" onSubmit={e=>{e.preventDefault();execute('take a note '+note);setNote('');}}><textarea placeholder="Something worth remembering…" aria-label="New note" value={note} onChange={e=>setNote(e.target.value)}/><button className="button primary" disabled={!canCommand||!note.trim()}><Plus size={15}/> Save note</button></form><div className="memory-items">{snapshot.notes.map(item=><article className="note" key={item.id}><span>NOTE {String(item.id).padStart(2,'0')}<small>{new Date(item.created*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'})}</small></span><p>{item.content}</p></article>)}{!snapshot.notes.length&&<div className="inline-empty">Say “take a note” followed by what you want to remember.</div>}</div></section><section className="panel"><div className="section-heading"><h3><Clock3 size={18}/> Upcoming reminders</h3><span>{snapshot.reminders.length} PENDING</span></div><form className="memory-form" onSubmit={e=>{e.preventDefault();execute('remind me '+reminder);setReminder('');}}><input aria-label="New reminder" placeholder="in 10 minutes to stretch" value={reminder} onChange={e=>setReminder(e.target.value)}/><button className="button primary" disabled={!canCommand||!reminder.trim()}><Plus size={15}/> Add reminder</button><small>Keep Jarvis running to receive your reminders.</small></form><div className="memory-items">{snapshot.reminders.map(item=><article className="reminder" key={item.id}><Clock3 size={18}/><div><p>{item.text}</p><span>{new Date(item.due*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</span></div><button className="icon-button" disabled={!canCommand} aria-label={`Cancel reminder ${item.id}`} onClick={()=>execute(`cancel reminder ${item.id}`)}><X size={16}/></button></article>)}{!snapshot.reminders.length&&<div className="inline-empty">All clear. Your next reminder will appear here.</div>}</div></section></div>
        </>}
        {page==='settings'&&<SettingsPage snapshot={snapshot} connected={connected} save={saveSettings} setup={setup} download={()=>void run(async()=>{setSetup({message:'Preparing local models…',running:true});try{await request('download_models');}catch(e){setSetup({message:String(e),running:false});throw e;}})} onError={setError}/>}
      </main>
      <footer className="statusbar"><span><i className={snapshot.listening?'online':''}/>{connected?(snapshot.listening?'Microphone active':'Microphone paused'):'Desktop connection required'}</span><span>{snapshot.settings.language==='ur'?'Urdu':snapshot.settings.language==='en'?'English':'English + Urdu'}<i/>Local processing<i/><span className="shortcut-label">Ctrl + Alt + J to speak</span></span></footer>
    </section>
    {notification&&<div className="toast reminder-toast" role="status"><Clock3 size={19}/><div><strong>Jarvis reminder</strong><p>{notification}</p></div><button className="icon-button" aria-label="Dismiss reminder" onClick={()=>setNotification('')}><X size={17}/></button></div>}
    {error&&<div className="toast" role="alert"><AlertCircle size={19}/><div><strong>Jarvis needs your attention</strong><p>{error}</p></div><button className="icon-button" aria-label="Dismiss error" onClick={()=>setError('')}><X size={17}/></button></div>}
    {aliasFile&&<div className="modal-backdrop"><form className="modal" role="dialog" aria-modal="true" aria-labelledby="alias-title" onSubmit={e=>{e.preventDefault();void run(async()=>{await saveSettings({aliases:{...snapshot.settings.aliases,[aliasName.trim().toLowerCase()]:aliasFile.path}});setAliasFile(null);});}}><span className="eyebrow">MAKE IT EASY TO SAY</span><h2 id="alias-title">Give this file a voice name.</h2><p>{aliasFile.name}</p><input autoFocus aria-label="Voice name" placeholder="For example, my budget" value={aliasName} onChange={e=>setAliasName(e.target.value)}/><div><button type="button" className="button" onClick={()=>setAliasFile(null)}>Cancel</button><button className="button primary" disabled={!aliasName.trim()}>Save voice name</button></div></form></div>}
  </div>;
}
