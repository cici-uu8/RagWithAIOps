class LoadingStateManager {
    constructor() {
        this.states = {
            chat: [
                { text: '正在检索知识库...', progress: 30, duration: 2000 },
                { text: '正在分析相关文档...', progress: 60, duration: 3000 },
                { text: '正在生成回答...', progress: 90, duration: 5000 },
            ],
            file_upload: [
                { text: '正在上传文件...', progress: 20, duration: 1000 },
                { text: '正在解析内容...', progress: 50, duration: 3000 },
                { text: '正在建立向量索引...', progress: 80, duration: 4000 },
                { text: '文档已添加到知识库', progress: 100, duration: 1000 },
            ],
            aiops: [
                { text: '正在制定诊断计划...', progress: 25, duration: 2000 },
                { text: '正在查询监控数据...', progress: 50, duration: 3000 },
                { text: '正在分析诊断结果...', progress: 75, duration: 4000 },
                { text: '正在生成诊断报告...', progress: 95, duration: 2000 },
            ],
        };
    }

    start(type, containerOrId, options = {}) {
        const container = this.resolveContainer(containerOrId);
        if (!container) return this.noopHandle();

        const states = this.states[type] || this.states.chat;
        const loadingCard = this.createLoadingCard(options);
        const shouldAppend = options.append !== false;
        if (shouldAppend) {
            container.appendChild(loadingCard);
        }

        const textElement = loadingCard.querySelector('.loading-state-text');
        const progressBar = loadingCard.querySelector('.loading-progress-bar');
        let currentIndex = 0;
        let stopped = false;
        let timer = null;

        const updateState = () => {
            if (stopped || currentIndex >= states.length) return;

            const state = states[currentIndex];
            if (textElement) textElement.textContent = state.text;
            if (progressBar) progressBar.style.width = `${state.progress}%`;

            currentIndex += 1;
            if (currentIndex < states.length) {
                timer = window.setTimeout(updateState, state.duration);
            }
        };

        updateState();

        return {
            element: loadingCard,
            stop: () => {
                stopped = true;
                if (timer) {
                    window.clearTimeout(timer);
                }
                if (loadingCard.parentNode) {
                    loadingCard.parentNode.removeChild(loadingCard);
                }
            },
        };
    }

    attach(type, loadingElement) {
        if (!loadingElement) return this.noopHandle();
        const content = loadingElement.querySelector('.message-content') || loadingElement;
        return this.start(type, content, {
            append: true,
            compact: true,
        });
    }

    bindOverlay(type, overlayElement, options = {}) {
        if (!overlayElement) return this.noopHandle();

        const content = overlayElement.querySelector('.loading-content') || overlayElement;
        const textElement = overlayElement.querySelector('.loading-text');
        const subtextElement = overlayElement.querySelector('.loading-subtext');

        const handle = this.start(type, content, {
            append: true,
            overlay: true,
        });

        if (textElement && handle.element) {
            const stateText = handle.element.querySelector('.loading-state-text');
            if (stateText) {
                textElement.textContent = stateText.textContent;
                const observer = new MutationObserver(() => {
                    textElement.textContent = stateText.textContent;
                });
                observer.observe(stateText, { childList: true, characterData: true, subtree: true });
                const originalStop = handle.stop;
                handle.stop = () => {
                    observer.disconnect();
                    originalStop();
                };
            }
        }

        if (subtextElement) {
            subtextElement.textContent = options.subtext || '请稍候';
        }

        return handle;
    }

    createLoadingCard(options = {}) {
        const loadingCard = document.createElement('div');
        loadingCard.className = options.compact
            ? 'loading-state-card loading-state-card-compact'
            : 'loading-state-card';
        if (options.overlay) {
            loadingCard.classList.add('loading-state-card-overlay');
        }
        loadingCard.innerHTML = `
            <div class="loading-state-text"></div>
            <div class="loading-progress" aria-hidden="true">
                <div class="loading-progress-bar"></div>
            </div>
        `;
        return loadingCard;
    }

    resolveContainer(containerOrId) {
        if (!containerOrId) return null;
        if (typeof containerOrId === 'string') {
            return document.getElementById(containerOrId);
        }
        return containerOrId;
    }

    noopHandle() {
        return {
            element: null,
            stop: () => {},
        };
    }
}

window.loadingStateManager = new LoadingStateManager();
