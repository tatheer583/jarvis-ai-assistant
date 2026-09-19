"""Bounded offline hardware probe. No recording; playback requires --play.

With no reference, the built-in alba voice tests the engine, not personal cloning.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def child(args):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HOME'] = str(Path(args.directory) / 'voice/model/huggingface')
    import socket
    def offline(*_args, **_kwargs):
        raise RuntimeError('Network disabled')
    socket.socket.connect = offline
    socket.socket.connect_ex = offline
    import contextlib
    channel = sys.stdout
    def stage(name):
        channel.write(json.dumps({'stage': name}) + '\n')
        channel.flush()
    with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        try:
            stage('importing')
            import torch
            from pocket_tts import TTSModel
            stage('imported')
            if not args.load_model:
                return
            import psutil
            if psutil.virtual_memory().available < 1536 * 1024**2:
                stage('insufficient_free_memory')
                return
            torch.set_num_threads(2)
            model = TTSModel.load_model()
            stage('model_loaded')
            if args.reference and not model.has_voice_cloning:
                stage('weights_do_not_support_cloning')
                return
            state = model.get_state_for_audio_prompt(args.reference or 'alba')
            with torch.inference_mode():
                audio = model.generate_audio(state, 'Hello. Your local assistant is ready.')
            stage('audio_generated')
            if args.play:
                import sounddevice as sd
                sd.play(audio.detach().cpu().numpy(), model.sample_rate, blocking=True)
                stage('playback_completed')
        except Exception as exc:
            # Do not propagate exception text, which may contain reference paths.
            stage('failed_' + type(exc).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--load-model', action='store_true')
    parser.add_argument('--play', action='store_true')
    parser.add_argument('--reference')
    parser.add_argument('--consent', action='store_true')
    parser.add_argument('--timeout', type=int, default=60)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--directory', default='', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.reference:
        if not args.consent:
            parser.error('--reference requires --consent for your own recording')
        from Backend.PersonalVoice import validate_reference
        validate_reference(args.reference)
    if args.child:
        child(args)
        return
    from Backend.Config import data_directory
    import psutil
    directory = data_directory()
    command = [sys.executable, '-u', str(Path(__file__).resolve()), *sys.argv[1:], '--child', '--directory', str(directory)]
    started = time.monotonic()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    peak = cpu = 0
    reason = ''
    while process.poll() is None:
        try:
            items = [psutil.Process(process.pid)]
            items += items[0].children(recursive=True)
            peak = max(peak, sum(p.memory_info().rss for p in items))
            cpu = max(cpu, sum(p.cpu_times().user + p.cpu_times().system for p in items))
            if peak > 2304 * 1024**2 or time.monotonic() - started > args.timeout:
                reason = 'memory_limit' if peak > 2304 * 1024**2 else 'timeout'
                for item in reversed(items):
                    try: item.terminate()
                    except psutil.NoSuchProcess: pass
                break
        except psutil.NoSuchProcess:
            break
        time.sleep(0.1)
    output, _ = process.communicate(timeout=10)
    stages = [json.loads(line)['stage'] for line in output.splitlines() if line.startswith('{')]
    report = {'stages': stages, 'blocked': reason, 'exit_code': process.returncode,
              'elapsed_seconds': round(time.monotonic() - started, 2),
              'peak_working_set_mb': round(peak / 1024**2, 1), 'cpu_seconds': round(cpu, 2),
              'personal_reference_used': bool(args.reference), 'play_requested': args.play}
    print(json.dumps(report, indent=2))
    if reason or any(s.startswith('failed_') or s in {'insufficient_free_memory', 'weights_do_not_support_cloning'} for s in stages):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
