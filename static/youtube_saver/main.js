document.addEventListener('DOMContentLoaded', () => {
    const currentPath = window.location.pathname.replace(/\/$/, '');
    const navLinks = document.querySelectorAll('nav a');

    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (!href) return;
        const normalized = href.replace(/\/$/, '');
        if (normalized && currentPath.endsWith(normalized)) {
            link.classList.add('active');
        }
    });

    const videoGrid = document.getElementById('videoGrid');
    if (videoGrid && videoGrid.dataset.source === 'mock') {
        const mockVideos = [
            { id: 'v1', title: 'Relaxing Jazz Music - Background Music for Work, Study', thumbnail: 'https://img.youtube.com/vi/Dx5qFacchBC/maxresdefault.jpg', length: '3:45:12' },
            { id: 'v2', title: 'Lofi Hip Hop Radio - Beats to Relax/Study to', thumbnail: 'https://img.youtube.com/vi/5qap5aO4i9A/maxresdefault.jpg', length: 'live' },
            { id: 'v3', title: 'Top 10 Programming Languages to Learn in 2024', thumbnail: 'https://img.youtube.com/vi/bJzb-RuUcMU/maxresdefault.jpg', length: '12:34' },
            { id: 'v4', title: 'Glassmorphism CSS Tutorial | Glass Effect', thumbnail: 'https://img.youtube.com/vi/W4vXCAJCCG4/maxresdefault.jpg', length: '8:21' },
            { id: 'v5', title: 'Beautiful Nature 4K Video Ultra HD', thumbnail: 'https://img.youtube.com/vi/IpIv5k4yVb0/maxresdefault.jpg', length: '1:00:05' },
            { id: 'v6', title: 'Cyberpunk 2077 - Official Cinematic Trailer', thumbnail: 'https://img.youtube.com/vi/8X2kIfS6fb8/maxresdefault.jpg', length: '4:15' },
        ];
        renderVideos(mockVideos);
    }

    const searchInput = document.querySelector('.search-input');
    if (searchInput && videoGrid) {
        searchInput.addEventListener('input', (e) => {
            const term = e.target.value.toLowerCase();
            const cards = videoGrid.querySelectorAll('.video-card');
            cards.forEach(card => {
                const title = (card.dataset.title || '').toLowerCase();
                card.style.display = title.includes(term) ? '' : 'none';
            });
        });
    }

    function renderVideos(videos) {
        if (!videoGrid) return;
        videoGrid.innerHTML = '';
        videos.forEach(video => {
            const card = document.createElement('div');
            card.className = 'glass-panel video-card';
            card.dataset.id = video.id;
            card.dataset.title = video.title;

            card.innerHTML = `
                <img src="${video.thumbnail}" alt="${video.title}" class="video-thumb">
                <div class="video-info">
                    <h3 class="video-title">${video.title}</h3>
                    <div class="video-meta">
                        <span>${video.length}</span>
                        <span>YouTube</span>
                    </div>
                </div>
                <div class="card-select"><i class="fas fa-check"></i></div>
            `;

            videoGrid.appendChild(card);
        });
    }
});
