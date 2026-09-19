import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';
const overlay = new URLSearchParams(location.search).get('overlay');
if (overlay === 'grid') document.documentElement.classList.add('grid-mode');
createRoot(document.getElementById('root')!).render(overlay === 'grid'
  ? <div className="mouse-grid">{Array.from({length:9},(_,i)=><div key={i}><span>{i+1}</span></div>)}<small>JARVIS · Say zoom five or click a number · Hide grid to cancel</small></div>
  : <App/>);
