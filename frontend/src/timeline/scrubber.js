/**
 * Timeline scrubber — drag to replay history or animate forecast forward.
 */
const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';
let _frames = [];
let _currentIndex = 0;
let _playing = false;
let _speed = 4;
let _animationId = null;
let _onFrameChange = null;

export async function initTimeline(onFrameChange) {
    _onFrameChange = onFrameChange;
    try {
        const resp = await fetch(`${API}/timeline/frames?start=-72h&end=+240h&step=6h`);
        const data = await resp.json();
        _frames = data.frames || [];
    } catch (e) {
        console.warn('Timeline frames unavailable:', e);
        _frames = [];
    }

    const slider = document.getElementById('timeline-slider');
    if (slider) {
        slider.max = Math.max(1, _frames.length - 1);
        slider.value = Math.floor(_frames.length / 2); // Start at NOW
        slider.addEventListener('input', (e) => {
            _currentIndex = parseInt(e.target.value);
            updateDisplay();
            if (_onFrameChange && _frames[_currentIndex]) _onFrameChange(_frames[_currentIndex]);
        });
    }

    document.getElementById('timeline-play')?.addEventListener('click', play);
    document.getElementById('timeline-pause')?.addEventListener('click', pause);
    document.getElementById('timeline-speed')?.addEventListener('change', (e) => { _speed = parseInt(e.target.value); });

    updateDisplay();
}

function play() {
    _playing = true;
    document.getElementById('timeline-play').style.display = 'none';
    document.getElementById('timeline-pause').style.display = '';
    animate();
}

function pause() {
    _playing = false;
    document.getElementById('timeline-play').style.display = '';
    document.getElementById('timeline-pause').style.display = 'none';
    if (_animationId) cancelAnimationFrame(_animationId);
}

let _lastTick = 0;
function animate(timestamp) {
    if (!_playing) return;
    if (timestamp - _lastTick > (1000 / _speed)) {
        _lastTick = timestamp;
        _currentIndex = (_currentIndex + 1) % _frames.length;
        const slider = document.getElementById('timeline-slider');
        if (slider) slider.value = _currentIndex;
        updateDisplay();
        if (_onFrameChange && _frames[_currentIndex]) _onFrameChange(_frames[_currentIndex]);
    }
    _animationId = requestAnimationFrame(animate);
}

function updateDisplay() {
    const frame = _frames[_currentIndex];
    if (!frame) return;
    const el = document.getElementById('timeline-current');
    if (el) el.textContent = frame.relative || 'NOW';
    const phase = document.getElementById('timeline-phase');
    if (phase) phase.textContent = frame.phase || 'MONITORING';
}

export function getCurrentFrame() { return _frames[_currentIndex]; }
export function getFrames() { return _frames; }
