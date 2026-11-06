<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { invoke } from '@tauri-apps/api/core';
  import { listen } from '@tauri-apps/api/event';
  import { open } from '@tauri-apps/plugin-dialog';
  import { getCurrentWindow } from '@tauri-apps/api/window';

  type Screen = 'Download' | 'Queue' | 'History' | 'Settings';
  type Spec = {
    url: string; output_dir: string; title: string; mode: string; video_quality: string;
    video_container: string; audio_format: string; subtitle_mode: string; subtitle_languages: string;
    automatic_subtitles: boolean; embed_metadata: boolean; embed_thumbnail: boolean;
    playlist_mode: string; playlist_start: number | null; playlist_end: number | null;
    overwrite: string; cookie_source: string; browser: string; cookie_file: string; proxy: string;
    rate_limit_kbps: number | null; retries: number; extra_args: string[];
  };
  type Job = { id: string; spec: Spec; status: string; percent: number; speed: string; eta: string; log: string[] };
  const initial: Spec = {
    url: '', output_dir: '', title: '', mode: 'video', video_quality: 'Best', video_container: 'Auto',
    audio_format: 'mp3', subtitle_mode: 'None', subtitle_languages: 'en', automatic_subtitles: false,
    embed_metadata: true, embed_thumbnail: false, playlist_mode: 'Single video', playlist_start: null,
    playlist_end: null, overwrite: 'Skip existing', cookie_source: 'None', browser: 'chrome',
    cookie_file: '', proxy: '', rate_limit_kbps: null, retries: 10, extra_args: []
  };
  let screen: Screen = $state('Download');
  let spec: Spec = $state({ ...initial });
  let settings: Record<string, unknown> = $state({});
  let jobs: Job[] = $state([]);
  let history: Record<string, unknown>[] = $state([]);
  let preview: Record<string, unknown> | null = $state(null);
  let thumbnailFailed = $state(false);
  let analyzing = $state(false);
  let analysisError = $state('');
  let linkError = $state('');
  let optionsOpen = $state(false);
  let destinationOpen = $state(false);
  let startNow = $state(true);
  let pendingFolder = $state('');
  let destinationError = $state('');
  let commandPreview = $state('');
  let expertInput = $state('');
  let status = $state('Ready');
  let previousFocus: HTMLElement | null = null;

  onMount(() => {
    if (!('__TAURI_INTERNALS__' in window)) { status = 'Design preview'; return; }
    invoke<{settings: Record<string, unknown>; history: Record<string, unknown>[]; jobs?: Job[]}>('bootstrap')
      .then(data => {
        settings = data.settings;
        history = data.history;
        jobs = data.jobs ?? [];
        spec.output_dir = String(settings.download_dir || '');
        for (const key of ['mode', 'video_quality', 'video_container', 'audio_format', 'subtitle_mode',
          'subtitle_languages', 'automatic_subtitles', 'embed_metadata', 'embed_thumbnail', 'overwrite', 'retries', 'rate_limit_kbps']) {
          if (settings[key] !== undefined) (spec as unknown as Record<string, unknown>)[key] = settings[key];
        }
      }).catch(error => status = String(error));
    const subscription = listen<Job[]>('queue-updated', event => jobs = event.payload);
    const historySubscription = listen<Record<string, unknown>[]>('history-updated', event => history = event.payload);
    const closeSubscription = getCurrentWindow().onCloseRequested(async event => {
      const active = jobs.find(job => job.status === 'Downloading');
      if (!active) return;
      event.preventDefault();
      if (!confirm('A download is still running. Stop it and close the app?')) return;
      await invoke('queue_action', { action: 'stop_and_wait', id: null });
      await getCurrentWindow().destroy();
    });
    return () => { subscription.then(unlisten => unlisten()); historySubscription.then(unlisten => unlisten()); closeSubscription.then(unlisten => unlisten()); };
  });

  function changedLink() {
    preview = null; thumbnailFailed = false; analysisError = ''; linkError = '';
    spec.playlist_mode = 'Single video'; spec.playlist_start = null; spec.playlist_end = null;
  }

  async function analyze() {
    linkError = '';
    if (!/^https?:\/\/[^\s/]+/i.test(spec.url.trim())) { linkError = 'Enter a complete http:// or https:// link.'; return; }
    analyzing = true; analysisError = ''; preview = null; thumbnailFailed = false;
    try {
      preview = await invoke<Record<string, unknown>>('analyze', { spec });
      spec.title = String(preview.title || '');
      if (preview._type === 'playlist' || preview.entries) spec.playlist_mode = 'Full playlist';
      status = 'Link analyzed';
    } catch (error) {
      analysisError = String(error);
      status = 'Analysis unavailable';
    } finally { analyzing = false; }
  }

  async function cancelAnalysis() {
    await invoke('cancel_analysis');
    analyzing = false;
    analysisError = 'Analysis canceled. You can download with defaults.';
  }

  async function openOptions() {
    try { spec.extra_args = parseExpert(expertInput); } catch (error) { status = String(error); return; }
    try { commandPreview = 'yt-dlp.exe ' + (await invoke<string[]>('command_preview', { spec: { ...spec, output_dir: String(settings.download_dir || spec.output_dir) } })).map(argument => JSON.stringify(argument)).join(' '); }
    catch { commandPreview = 'Choose a destination before previewing the command.'; }
    previousFocus = document.activeElement as HTMLElement;
    optionsOpen = true;
    await tick(); document.querySelector<HTMLElement>('.dialog.options select, .dialog.options input')?.focus();
  }

  function requestDestination(now: boolean) {
    linkError = '';
    if (!/^https?:\/\/[^\s/]+/i.test(spec.url.trim())) { linkError = 'Enter a complete http:// or https:// link.'; return; }
    if (spec.playlist_mode === 'Playlist range' && (!spec.playlist_start || !spec.playlist_end || spec.playlist_end < spec.playlist_start)) {
      linkError = 'Enter a valid playlist start and end.'; return;
    }
    previousFocus = document.activeElement as HTMLElement;
    startNow = now; pendingFolder = String(settings.download_dir || spec.output_dir || ''); destinationError = ''; destinationOpen = true;
    tick().then(() => document.querySelector<HTMLElement>('#destination')?.focus());
  }

  function closeDialog(which: 'options' | 'destination') {
    if (which === 'options') optionsOpen = false; else destinationOpen = false;
    tick().then(() => previousFocus?.focus());
  }

  function dialogKey(event: KeyboardEvent, which: 'options' | 'destination') {
    if (event.key === 'Escape') { event.preventDefault(); closeDialog(which); return; }
    if (event.key !== 'Tab') return;
    const items = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary')];
    const first = items[0], last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }

  async function confirmDestination() {
    if (!pendingFolder.trim()) { destinationError = 'Choose a download folder.'; return; }
    try {
      spec.extra_args = parseExpert(expertInput);
      await invoke('add_job', { spec: { ...spec, output_dir: pendingFolder }, startNow });
      closeDialog('destination'); screen = 'Queue'; status = startNow ? 'Download started' : 'Added to queue';
    } catch (error) { destinationError = String(error); }
  }

  async function saveSettings() {
    try { await invoke('save_settings', { settings }); spec.retries = Number(settings.retries); spec.rate_limit_kbps = settings.rate_limit_kbps == null ? null : Number(settings.rate_limit_kbps); status = 'Settings saved'; }
    catch (error) { status = String(error); }
  }

  function parseExpert(input: string): string[] {
    const result: string[] = []; let part = ''; let quoted = false; let started = false;
    for (let i = 0; i < input.length; i++) {
      const char = input[i];
      if (char === '\\') {
        let count = 1; while (input[i + count] === '\\') count++;
        if (input[i + count] === '"') {
          part += '\\'.repeat(Math.floor(count / 2));
          if (count % 2) part += '"'; else quoted = !quoted;
          i += count;
        } else { part += '\\'.repeat(count); i += count - 1; }
        started = true;
      } else if (char === '"') { quoted = !quoted; started = true; }
      else if (/\s/.test(char) && !quoted) { if (started) { result.push(part); part = ''; started = false; } }
      else { part += char; started = true; }
    }
    if (quoted) throw new Error('Finish the quote in expert arguments.');
    if (started) result.push(part);
    return result;
  }

  async function chooseFolder(target: 'job' | 'default') {
    const selected = await open({ directory: true, multiple: false, title: 'Choose download folder' });
    if (typeof selected === 'string') {
      if (target === 'job') pendingFolder = selected;
      else settings.download_dir = selected;
    }
  }

  async function queueAction(action: string, id?: string) {
    try { await invoke('queue_action', { action, id: id ?? null }); }
    catch (error) { status = String(error); }
  }

  async function clearHistory() {
    if (!confirm('Clear successful download history from this computer?')) return;
    try { await invoke('clear_history'); history = []; status = 'History cleared'; }
    catch (error) { status = String(error); }
  }

  function retryHistory(item: Record<string, unknown>) {
    const old = item.spec as Partial<Spec> | undefined;
    const safeUrl = String(item.url || '');
    const url = safeUrl || prompt('This link may contain private access information. Paste it again to download:', '') || '';
    if (!url) return;
    spec = { ...initial, ...old, url, cookie_source: spec.cookie_source, browser: spec.browser,
      cookie_file: spec.cookie_file, proxy: spec.proxy, extra_args: [], output_dir: String(item.output_dir || settings.download_dir || '') };
    preview = null; analysisError = ''; linkError = ''; screen = 'Download';
    requestDestination(true);
  }

  async function openHistoryFolder(item: Record<string, unknown>) {
    try { await invoke('open_folder', { path: String(item.output_dir || '') }); }
    catch (error) { status = String(error); }
  }
</script>

<svelte:head><title>Unofficial yt-dlp Desktop</title></svelte:head>

<div class="app">
  <header class="topbar">
    <div class="brand"><span class="brand-mark">▶</span><span>yt-dlp <small>Desktop</small></span></div>
    <nav aria-label="Main navigation">
      {#each ['Download', 'Queue', 'History', 'Settings'] as item}
        <button class:active={screen === item} onclick={() => screen = item as Screen} aria-current={screen === item ? 'page' : undefined}>{item}{#if item === 'Queue' && jobs.length}<span class="count">{jobs.length}</span>{/if}</button>
      {/each}
    </nav>
  </header>

  {#if screen === 'Download'}
    <main class="download">
      <div class="heading"><div><p class="eyebrow">YOUR MEDIA, YOUR FOLDER</p><h1>Download</h1><p class="intro">Paste a link and choose what to save.</p></div></div>
      <label for="url">Video or playlist link</label>
      <div class="link-row"><input id="url" type="url" placeholder="https://www.youtube.com/watch?v=…" bind:value={spec.url} oninput={changedLink} aria-invalid={!!linkError} aria-describedby={linkError ? 'link-error' : undefined} /><button class="secondary" onclick={analyzing ? cancelAnalysis : analyze}>{analyzing ? 'Cancel' : 'Analyze'}</button></div>
      {#if linkError}<p id="link-error" class="error" role="alert">{linkError}</p>{/if}
      {#if analyzing}<div class="preview loading" role="status"><span class="spinner"></span><div><strong>Looking up this link</strong><small>Checking title, formats, and playlist details…</small></div></div>
      {:else if preview}<div class="preview">{#if !thumbnailFailed && typeof preview.thumbnail === 'string' && preview.thumbnail.startsWith('https://')}<img class="preview-image" src={preview.thumbnail} alt="" loading="lazy" decoding="async" onerror={() => thumbnailFailed = true} />{:else}<div class="preview-icon">▶</div>{/if}<div class="preview-copy"><strong>{String(preview.title || 'Untitled media')}</strong><small>{String(preview.extractor_key || preview.extractor || 'Supported media')} · {preview.duration ? (Number(preview.duration) < 60 ? `${Math.round(Number(preview.duration))} sec` : `${Math.round(Number(preview.duration) / 60)} min`) : 'Ready to download'}</small></div><span class="success">Ready</span></div>
      {:else if analysisError}<div class="preview problem" role="status"><div class="preview-icon">!</div><div class="preview-copy"><strong>Analysis unavailable</strong><small>{analysisError} Download with defaults is still available.</small></div></div>
      {:else}<div class="preview empty"><div class="preview-icon">↗</div><div class="preview-copy"><strong>Ready when you are</strong><small>Analyze to see details, or download with defaults.</small></div></div>{/if}

      {#if preview && (preview._type === 'playlist' || preview.entries)}
        <div class="playlist-row"><label for="playlist">Playlist</label><select id="playlist" bind:value={spec.playlist_mode}><option>Full playlist</option><option>Single video</option><option>Playlist range</option></select>
          {#if spec.playlist_mode === 'Playlist range'}<label class="sr-only" for="range-start">Start</label><input id="range-start" type="number" min="1" placeholder="Start" bind:value={spec.playlist_start} /><label class="sr-only" for="range-end">End</label><input id="range-end" type="number" min="1" placeholder="End" bind:value={spec.playlist_end} />{/if}</div>
        {#if spec.playlist_mode === 'Playlist range' && spec.playlist_start && spec.playlist_end && spec.playlist_end < spec.playlist_start}<p class="error" role="alert">End must be after start.</p>{/if}
      {/if}

      <section class="choice" aria-label="Download choices"><div class="mode"><span class="field-label">Save as</span><div class="segment" role="group" aria-label="Save as"><button class:selected={spec.mode === 'video'} onclick={() => spec.mode = 'video'}>Video</button><button class:selected={spec.mode === 'audio'} onclick={() => spec.mode = 'audio'}>Audio</button></div></div>
        {#if spec.mode === 'video'}<div class="select-field"><label for="quality">Quality</label><select id="quality" bind:value={spec.video_quality}>{#each ['Best','2160p','1440p','1080p','720p','480p'] as q}<option>{q}</option>{/each}</select></div><div class="select-field"><label for="container">Container</label><select id="container" bind:value={spec.video_container}>{#each ['Auto','MP4','MKV'] as c}<option>{c}</option>{/each}</select></div>
        {:else}<div class="select-field"><label for="audio-format">Audio format</label><select id="audio-format" bind:value={spec.audio_format}>{#each ['mp3','m4a','opus','flac','wav'] as f}<option>{f}</option>{/each}</select></div>{/if}</section>
      <div class="actions"><button class="text-button" onclick={openOptions}>⚙ &nbsp;Options</button><div class="action-end"><button class="secondary" onclick={() => requestDestination(false)}>Add to queue</button><button class="primary" onclick={() => requestDestination(true)}>{analysisError ? 'Download with defaults' : 'Download'}</button></div></div>
    </main>
  {:else if screen === 'Queue'}
    <main class="content"><div class="section-head"><div><h1>Queue</h1><p class="intro">Downloads run one at a time.</p></div><button class="secondary" onclick={() => screen = 'Download'}>New download</button></div>
      <div class="queue-tools"><button class="secondary" onclick={() => queueAction('resume')}>Start queue</button><button class="text-button" onclick={() => queueAction('pause')}>Pause before next</button></div>
      {#if jobs.length === 0}<div class="empty-state"><span>⇩</span><h2>Nothing in the queue</h2><p>Your downloads will appear here.</p></div>{:else}<div class="job-list">{#each jobs as job}<article class="job"><div><strong>{job.spec.title || job.spec.url}</strong><small>{job.status} · {job.speed} {job.eta}</small><div class="job-actions">{#if job.status === 'Downloading'}<button onclick={() => queueAction('stop', job.id)}>Stop</button>{:else}<button onclick={() => queueAction('up', job.id)} aria-label="Move download up">↑</button><button onclick={() => queueAction('down', job.id)} aria-label="Move download down">↓</button><button onclick={() => queueAction(job.status === 'Failed' ? 'retry' : 'remove', job.id)}>{job.status === 'Failed' ? 'Retry' : 'Remove'}</button>{/if}</div>{#if job.log.length}<details><summary>Log</summary><pre>{job.log.join('\n')}</pre></details>{/if}</div><progress max="100" value={job.percent} aria-label="Download progress"></progress></article>{/each}</div>{/if}
    </main>
  {:else if screen === 'History'}
    <main class="content"><div class="section-head"><div><h1>History</h1><p class="intro">Your latest successful downloads.</p></div><button class="secondary" onclick={clearHistory}>Clear history</button></div>
      {#if history.length === 0}<div class="empty-state"><span>◷</span><h2>No downloads yet</h2><p>Completed files appear here.</p></div>{:else}<div class="job-list">{#each history as item}<article class="history-item"><div><strong>{String(item.title || 'Completed download')}</strong><small>{String(item.completed_at || '')}</small></div><div class="job-actions"><button onclick={() => retryHistory(item)}>Download again</button><button onclick={() => openHistoryFolder(item)}>Open folder</button></div></article>{/each}</div>{/if}
    </main>
  {:else}
    <main class="content settings"><h1>Settings</h1><p class="intro">Defaults and explicit access for this session.</p><div class="settings-grid"><div><label for="default-folder">Default download folder</label><div class="link-row"><input id="default-folder" bind:value={settings.download_dir} placeholder="C:\Users\…\Videos" /><button class="secondary" onclick={() => chooseFolder('default')}>Change</button></div></div><div><label for="retries">Retries</label><input id="retries" type="number" min="0" max="100" bind:value={settings.retries} /></div><div><label for="cookie-source">Access for this session</label><select id="cookie-source" bind:value={spec.cookie_source}><option>None</option><option>Browser</option><option>Cookie file</option></select></div>{#if spec.cookie_source === 'Browser'}<div><label for="browser">Browser</label><select id="browser" bind:value={spec.browser}>{#each ['chrome','firefox','edge','brave','opera'] as browser}<option>{browser}</option>{/each}</select></div>{:else if spec.cookie_source === 'Cookie file'}<div><label for="cookie-file">Cookie file</label><input id="cookie-file" bind:value={spec.cookie_file} /></div>{/if}<div><label for="proxy">Proxy for this session</label><input id="proxy" bind:value={spec.proxy} placeholder="Optional" /></div><div><label for="rate">Rate limit (KB/s)</label><input id="rate" type="number" min="0" bind:value={settings.rate_limit_kbps} /></div></div><button class="primary" onclick={saveSettings}>Save defaults</button><section class="about" aria-label="About"><h2>About</h2><p>Unofficial yt-dlp Desktop 1.3.0 preview · yt-dlp 2026.10.26 · Deno 2.9.8 · FFmpeg N-128340-gf80a436ffd.</p><p>FFmpeg is distributed under GPLv3 with its <a href="https://github.com/yt-dlp/FFmpeg-Builds/releases/tag/autobuild-2026-11-02-22-51">build and source information</a>. This app is independent of the yt-dlp project.</p></section>
    </main>
  {/if}
  <footer role="status">{status}</footer>
</div>

{#if destinationOpen}<div class="overlay" role="presentation"><div class="dialog" role="dialog" aria-modal="true" aria-labelledby="destination-title" tabindex="-1" onkeydown={event => dialogKey(event, 'destination')}><h2 id="destination-title">Choose where to save</h2><p>This folder applies to this download.</p><label for="destination">Destination</label><div class="link-row"><input id="destination" bind:value={pendingFolder} placeholder="Choose a folder" /><button class="secondary" onclick={() => chooseFolder('job')}>Change</button></div>{#if destinationError}<p class="error" role="alert">{destinationError}</p>{/if}<div class="dialog-actions"><button class="secondary" onclick={() => closeDialog('destination')}>Cancel</button><button class="primary" onclick={confirmDestination}>{startNow ? 'Start download' : 'Add to queue'}</button></div></div></div>{/if}
{#if optionsOpen}<div class="overlay" role="presentation"><div class="dialog options" role="dialog" aria-modal="true" aria-labelledby="options-title" tabindex="-1" onkeydown={event => dialogKey(event, 'options')}><h2 id="options-title">Download options</h2><div class="option-fields">{#if spec.mode === 'video'}<label for="subtitles">Subtitles</label><select id="subtitles" bind:value={spec.subtitle_mode}><option>None</option><option>Embed</option><option>Separate file</option></select><label for="languages">Languages</label><input id="languages" bind:value={spec.subtitle_languages} placeholder="en" /><label class="check"><input type="checkbox" bind:checked={spec.automatic_subtitles} /> Include automatic subtitles</label>{/if}<label class="check"><input type="checkbox" bind:checked={spec.embed_metadata} /> Embed metadata</label><label class="check"><input type="checkbox" bind:checked={spec.embed_thumbnail} /> Embed thumbnail</label><label for="overwrite">If a file exists</label><select id="overwrite" bind:value={spec.overwrite}><option>Skip existing</option><option>Overwrite</option></select><label for="expert">Expert arguments</label><input id="expert" bind:value={expertInput} placeholder="Optional; can override choices" /></div><details><summary>Command preview</summary><code>{commandPreview}</code></details><div class="dialog-actions"><button class="primary" onclick={() => closeDialog('options')}>Done</button></div></div></div>{/if}

<style>
  :global(*) { box-sizing: border-box; }
  :global(html), :global(body) { margin: 0; min-height: 100%; background: #0e1116; color: #f2f5f7; font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif; }
  :global(button), :global(input), :global(select) { font: inherit; }
  :global(button:focus-visible), :global(input:focus-visible), :global(select:focus-visible), :global(summary:focus-visible) { outline: 2px solid #80b7ff; outline-offset: 2px; }
  .app { min-height: 100vh; display: flex; flex-direction: column; }
  .topbar { min-height: 62px; border-bottom: 1px solid #27313d; background: #151b23; display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 0 26px; }
  .brand { display: flex; align-items: center; gap: 10px; white-space: nowrap; font-weight: 700; letter-spacing: -.02em; }
  .brand small { color: #9ba6b2; font-size: .78rem; font-weight: 400; margin-left: 3px; }
  .brand-mark { width: 24px; height: 24px; border-radius: 6px; display: grid; place-items: center; font-size: 12px; background: #273c58; color: #8bbdff; }
  nav { display: flex; gap: 4px; } nav button { border: 0; background: transparent; color: #aab5c1; padding: 10px 15px; border-radius: 7px; cursor: pointer; } nav button:hover, nav button.active { color: #f2f5f7; background: #263142; } nav button.active { box-shadow: inset 0 -2px #3a8dff; }
  .count { margin-left: 6px; color: #8bbdff; }
  main { width: min(100% - 48px, 820px); margin: 0 auto; }
  .download { padding: 30px 0 20px; } .heading { margin-bottom: 25px; } .eyebrow { color: #7daef1; font-size: .72rem; letter-spacing: .14em; font-weight: 700; margin: 0 0 7px; } h1 { margin: 0; font-size: clamp(1.8rem, 3vw, 2.5rem); letter-spacing: -.045em; font-weight: 650; } .intro { color: #aab5c1; margin: 7px 0 0; }
  label, .field-label { display: block; font-size: .84rem; color: #c0ccd7; margin-bottom: 8px; }
  input:not([type=checkbox]), select { width: 100%; min-width: 0; min-height: 43px; border: 1px solid #344050; border-radius: 7px; padding: 0 13px; color: #f2f5f7; background: #1a222d; }
  input::placeholder { color: #92a0ae; } select { cursor: pointer; } button { cursor: pointer; }
  .link-row { display: flex; gap: 10px; } .link-row input { flex: 1; }
  .secondary, .primary, .text-button { border-radius: 7px; min-height: 42px; padding: 0 17px; font-weight: 600; }
  .secondary { border: 1px solid #354458; color: #e9eff6; background: #202b3a; } .secondary:hover { background: #2b3a4d; }
  .primary { border: 1px solid #398cff; background: #3a8dff; color: #071320; } .primary:hover { background: #66a7ff; }
  .text-button { background: transparent; border: 0; color: #b5c9df; padding-left: 0; } .text-button:hover { color: #fff; }
  .preview { display: flex; align-items: center; gap: 14px; min-height: 86px; margin: 18px 0 25px; padding: 15px 17px; border: 1px solid #2a3543; background: #171f29; border-radius: 10px; }
  .preview-icon { flex: none; width: 48px; height: 48px; display: grid; place-items: center; border: 1px solid #334155; border-radius: 8px; color: #9db7d4; font-size: 1.1rem; }
  .preview-image { flex: none; width: 104px; height: 58px; object-fit: cover; border-radius: 6px; background: #202b3a; }
  .preview-copy { flex: 1; min-width: 0; display: grid; gap: 4px; } .preview strong { font-size: 1rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .preview small { color: #a4afbc; font-size: .83rem; } .success { margin-left: auto; color: #9bcab2; font-size: .8rem; } .problem .preview-icon { color: #ffb5b5; } .spinner { width: 28px; height: 28px; border: 3px solid #3f5268; border-top-color: #3a8dff; border-radius: 50%; animation: spin .8s linear infinite; margin: 0 10px; } @keyframes spin { to { transform: rotate(360deg); } }
  .choice { display: grid; grid-template-columns: 1.25fr 1fr 1fr; gap: 12px; } .segment { display: flex; height: 43px; padding: 3px; border: 1px solid #344050; border-radius: 7px; background: #1a222d; } .segment button { flex: 1; border: 0; background: transparent; color: #aebcca; border-radius: 5px; } .segment button.selected { color: #fff; background: #32435a; box-shadow: 0 1px 3px #0005; }
  .actions { display: flex; align-items: center; justify-content: space-between; margin-top: 23px; } .action-end { display: flex; gap: 10px; }
  .playlist-row { display: flex; align-items: center; gap: 10px; margin: -9px 0 18px; } .playlist-row label { margin: 0; } .playlist-row select { max-width: 250px; } .playlist-row input { max-width: 85px; }
  footer { margin-top: auto; border-top: 1px solid #27313d; padding: 7px 20px; min-height: 32px; color: #8c99a8; font-size: .75rem; }
  .error { color: #ff9c9c; margin: 7px 0 0; font-size: .82rem; }
  .content { padding-top: 38px; } .section-head { display: flex; justify-content: space-between; align-items: center; } .empty-state { margin: 80px auto 0; text-align: center; color: #aab5c1; } .empty-state span { font-size: 2rem; color: #7195bd; } .empty-state h2 { color: #e6edf3; font-size: 1.2rem; margin-bottom: 5px; }
  .job-list { margin-top: 28px; border-top: 1px solid #2b3542; } .job, .history-item { padding: 16px 4px; border-bottom: 1px solid #2b3542; display: flex; gap: 20px; align-items: center; justify-content: space-between; } .job div, .history-item { min-width: 0; } .job strong, .history-item strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .job small, .history-item small { color: #aab5c1; } progress { accent-color: #3a8dff; width: 140px; }
  .queue-tools { display: flex; align-items: center; gap: 16px; margin-top: 25px; } .job-actions { display: flex; gap: 6px; margin-top: 9px; } .job-actions button { border: 0; color: #a9c7e9; background: transparent; padding: 3px 7px; border-radius: 4px; } .job-actions button:hover { background: #263142; }
  .job details { margin-top: 10px; } .job pre { max-height: 180px; max-width: min(70vw, 600px); overflow: auto; white-space: pre-wrap; font-size: .75rem; color: #b9c4d1; }
  .settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 30px 0; } .settings-grid > div:first-child { grid-column: 1 / -1; }
  .about { border-top: 1px solid #2b3542; margin-top: 30px; padding-bottom: 30px; color: #aab5c1; font-size: .85rem; } .about h2 { color: #f2f5f7; font-size: 1rem; margin: 18px 0 8px; } .about p { margin: 6px 0; } .about a { color: #8bbdff; }
  .overlay { position: fixed; inset: 0; background: #05080dbb; display: grid; place-items: center; padding: 16px; z-index: 10; } .dialog { width: min(100%, 480px); max-height: min(90vh, 640px); overflow: auto; border: 1px solid #3b4858; border-radius: 12px; background: #1a222d; box-shadow: 0 22px 80px #0009; padding: 25px; } .dialog h2 { margin: 0 0 5px; } .dialog p { color: #aab5c1; } .dialog-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 25px; } .option-fields { display: grid; gap: 8px; margin-top: 22px; } .option-fields label { margin: 7px 0 0; } .check { display: flex; align-items: center; gap: 9px; } .check input { accent-color: #3a8dff; } details { margin-top: 15px; color: #aab5c1; } details code { display: block; padding: 10px; overflow-wrap: anywhere; font-size: .75rem; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
  @media (max-width: 720px), (max-height: 600px) { .topbar { padding: 0 10px; min-height: 40px; gap: 8px; } .brand { font-size: .82rem; } .brand small, .eyebrow { display: none; } nav button { padding: 6px 9px; font-size: .78rem; } main { width: min(100% - 24px, 820px); } .download { padding-top: 9px; } .heading { margin-bottom: 11px; } h1 { font-size: 1.5rem; } .intro { display: none; } input:not([type=checkbox]), select { min-height: 36px; } .secondary, .primary, .text-button { min-height: 36px; padding: 0 11px; font-size: .82rem; } .preview { min-height: 55px; margin: 7px 0 10px; padding: 7px 10px; } .preview-icon { width: 34px; height: 34px; } .preview-image { width: 70px; height: 40px; } .preview small { display: none; } .preview strong { font-size: .88rem; } .choice { gap: 7px; } .segment { height: 36px; } .actions { margin-top: 8px; } label, .field-label { margin-bottom: 4px; font-size: .75rem; } .playlist-row { margin: 0 0 7px; } footer { padding: 4px 12px; min-height: 24px; } }
  @media (max-width: 530px) { .brand { display: none; } .topbar { justify-content: center; } .choice { grid-template-columns: 1fr 1fr; } .choice > :last-child { grid-column: 1 / -1; } .settings-grid { grid-template-columns: 1fr; } }
  @media (max-height: 430px) { .preview-icon, .preview-image { display: none; } .preview { min-height: 38px; margin: 4px 0 7px; padding: 5px 8px; } .heading { margin-bottom: 7px; } .download { padding-top: 5px; } .actions { margin-top: 4px; } .playlist-row { margin-bottom: 4px; } }
  @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
  @media (forced-colors: active) { .primary, .secondary, .segment button.selected, nav button.active { border: 1px solid ButtonText; } progress { accent-color: Highlight; } }
</style>
