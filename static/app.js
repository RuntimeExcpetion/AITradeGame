class TradingApp {
    constructor() {
        this.currentModelId = null;
        this.chartCanvas = null;
        this.chartData = [];
        this.refreshIntervals = {
            market: null,
            portfolio: null,
            trades: null
        };
        this.handleResize = null;
        this.init();
    }

    init() {
        this.chartCanvas = document.getElementById('accountChart');
        this.handleResize = () => this.renderChart();
        window.addEventListener('resize', this.handleResize);
        this.initEventListeners();
        this.loadModels();
        this.loadMarketPrices();
        this.startRefreshCycles();
        this.renderChart();
    }

    async requestJson(url, options = {}) {
        const { context = 'request', ...fetchOptions } = options;
        const method = (fetchOptions.method || 'GET').toUpperCase();
        const hasBody = Object.prototype.hasOwnProperty.call(fetchOptions, 'body');

        console.info(`[${context}] -> ${method} ${url}${hasBody ? ' (payload hidden)' : ''}`);

        let response;
        try {
            response = await fetch(url, fetchOptions);
        } catch (networkError) {
            console.error(`[${context}] Network error`, networkError);
            throw networkError;
        }

        const responseText = await response.text();
        console.info(`[${context}] <- ${response.status} ${response.statusText} (${response.url})`);

        if (!response.ok) {
            console.error(`[${context}] HTTP error`, {
                url: response.url,
                status: response.status,
                statusText: response.statusText,
                bodyPreview: responseText.slice(0, 200)
            });
            throw new Error(`HTTP ${response.status}`);
        }

        if (!responseText.trim()) {
            return null;
        }

        try {
            return JSON.parse(responseText);
        } catch (parseError) {
            console.error(`[${context}] JSON parse error`, parseError, {
                bodyPreview: responseText.slice(0, 200)
            });
            throw parseError;
        }
    }

    initEventListeners() {
        document.getElementById('addModelBtn').addEventListener('click', () => this.showModal());
        document.getElementById('closeModalBtn').addEventListener('click', () => this.hideModal());
        document.getElementById('cancelBtn').addEventListener('click', () => this.hideModal());
        document.getElementById('submitBtn').addEventListener('click', () => this.submitModel());
        document.getElementById('refreshBtn').addEventListener('click', () => this.refresh());

        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e.target.dataset.tab));
        });
    }

    async loadModels() {
        try {
            const models = await this.requestJson('/api/models', { context: 'loadModels' });

            if (!Array.isArray(models)) {
                console.error('[loadModels] Unexpected response format', models);
                return;
            }

            this.renderModels(models);

            if (models.length > 0 && !this.currentModelId) {
                this.selectModel(models[0].id);
            }
        } catch (error) {
            console.error('Failed to load models:', error);
        }
    }

    renderModels(models) {
        const container = document.getElementById('modelList');
        
        if (models.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无模型</div>';
            return;
        }

        container.innerHTML = models.map(model => `
            <div class="model-item ${model.id === this.currentModelId ? 'active' : ''}" 
                 onclick="app.selectModel(${model.id})">
                <div class="model-name">${model.name}</div>
                <div class="model-info">
                    <span>${model.model_name}</span>
                    <span class="model-delete" onclick="event.stopPropagation(); app.deleteModel(${model.id})">
                        <span class="icon" aria-hidden="true">🗑️</span>
                    </span>
                </div>
            </div>
        `).join('');
    }

    async selectModel(modelId) {
        this.currentModelId = modelId;
        this.loadModels();
        await this.loadModelData();
    }

    async loadModelData() {
        if (!this.currentModelId) return;

        try {
            const [portfolio, trades, conversations] = await Promise.all([
                this.requestJson(`/api/models/${this.currentModelId}/portfolio`, { context: 'loadModelData:portfolio' }),
                this.requestJson(`/api/models/${this.currentModelId}/trades?limit=50`, { context: 'loadModelData:trades' }),
                this.requestJson(`/api/models/${this.currentModelId}/conversations?limit=20`, { context: 'loadModelData:conversations' })
            ]);

            if (!portfolio || !portfolio.portfolio) {
                console.error('[loadModelData] Unexpected portfolio response', portfolio);
                return;
            }

            const tradeList = Array.isArray(trades) ? trades : [];
            const conversationList = Array.isArray(conversations) ? conversations : [];

            this.updateStats(portfolio.portfolio);
            this.updateChart(portfolio.account_value_history, portfolio.portfolio.total_value);
            this.updatePositions(portfolio.portfolio.positions);
            this.updateTrades(tradeList);
            this.updateConversations(conversationList);
        } catch (error) {
            console.error('Failed to load model data:', error);
        }
    }

    updateStats(portfolio) {
        const stats = [
            { value: portfolio.total_value || 0, class: portfolio.total_value > portfolio.initial_capital ? 'positive' : portfolio.total_value < portfolio.initial_capital ? 'negative' : '' },
            { value: portfolio.cash || 0, class: '' },
            { value: portfolio.realized_pnl || 0, class: portfolio.realized_pnl > 0 ? 'positive' : portfolio.realized_pnl < 0 ? 'negative' : '' },
            { value: portfolio.unrealized_pnl || 0, class: portfolio.unrealized_pnl > 0 ? 'positive' : portfolio.unrealized_pnl < 0 ? 'negative' : '' }
        ];

        document.querySelectorAll('.stat-value').forEach((el, index) => {
            if (stats[index]) {
                el.textContent = `$${Math.abs(stats[index].value).toFixed(2)}`;
                el.className = `stat-value ${stats[index].class}`;
            }
        });
    }

    updateChart(history, currentValue) {
        const sortedHistory = Array.isArray(history) ? [...history].reverse() : [];
        const data = sortedHistory.map(h => ({
            time: new Date(h.timestamp.replace(' ', 'T') + 'Z').toLocaleTimeString('zh-CN', {
                timeZone: 'Asia/Shanghai',
                hour: '2-digit',
                minute: '2-digit'
            }),
            value: h.total_value
        }));

        if (currentValue !== undefined && currentValue !== null) {
            const now = new Date();
            const currentTime = now.toLocaleTimeString('zh-CN', {
                timeZone: 'Asia/Shanghai',
                hour: '2-digit',
                minute: '2-digit'
            });
            data.push({
                time: currentTime,
                value: currentValue
            });
        }

        this.chartData = data;
        this.renderChart();
    }

    renderChart() {
        const canvas = this.chartCanvas || document.getElementById('accountChart');
        if (!canvas) return;

        const width = canvas.clientWidth;
        const height = canvas.clientHeight;

        if (width === 0 || height === 0) {
            return;
        }

        const dpr = window.devicePixelRatio || 1;
        canvas.width = width * dpr;
        canvas.height = height * dpr;

        const ctx = canvas.getContext('2d');
        if (!ctx) {
            return;
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, width, height);

        if (!this.chartData || this.chartData.length === 0) {
            ctx.fillStyle = '#86909c';
            ctx.font = '14px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('暂无数据', width / 2, height / 2);
            return;
        }

        const padding = { top: 20, right: 20, bottom: 30, left: 60 };
        const chartWidth = Math.max(width - padding.left - padding.right, 0);
        const chartHeight = Math.max(height - padding.top - padding.bottom, 0);

        if (chartWidth <= 0 || chartHeight <= 0) {
            return;
        }

        const values = this.chartData.map(point => point.value);
        const rawMin = Math.min(...values);
        const rawMax = Math.max(...values);

        let minValue = rawMin;
        let maxValue = rawMax;

        if (rawMax === rawMin) {
            const padding = rawMax === 0 ? 1 : Math.abs(rawMax) * 0.05;
            minValue = rawMin - padding;
            maxValue = rawMax + padding;
        }

        const range = maxValue - minValue || 1;

        const points = this.chartData.map((point, index) => {
            const xRatio = this.chartData.length > 1 ? index / (this.chartData.length - 1) : 0;
            const x = padding.left + chartWidth * xRatio;
            const yRatio = (point.value - minValue) / range;
            const y = padding.top + chartHeight - chartHeight * yRatio;
            return { ...point, x, y };
        });

        ctx.lineWidth = 1;
        ctx.font = '12px sans-serif';
        ctx.fillStyle = '#86909c';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        const horizontalSteps = 4;
        ctx.strokeStyle = '#f2f3f5';
        for (let i = 0; i <= horizontalSteps; i++) {
            const y = padding.top + (chartHeight / horizontalSteps) * i;
            ctx.beginPath();
            ctx.moveTo(padding.left, y);
            ctx.lineTo(width - padding.right, y);
            ctx.stroke();

            const value = rawMax === rawMin
                ? rawMax
                : maxValue - (range / horizontalSteps) * i;
            ctx.fillText(`$${value.toFixed(2)}`, padding.left - 10, y);
        }

        ctx.strokeStyle = '#e5e6eb';
        ctx.beginPath();
        ctx.moveTo(padding.left, padding.top);
        ctx.lineTo(padding.left, height - padding.bottom);
        ctx.lineTo(width - padding.right, height - padding.bottom);
        ctx.stroke();

        const gradient = ctx.createLinearGradient(0, padding.top, 0, height - padding.bottom);
        gradient.addColorStop(0, 'rgba(51, 112, 255, 0.2)');
        gradient.addColorStop(1, 'rgba(51, 112, 255, 0)');

        ctx.beginPath();
        points.forEach((point, index) => {
            if (index === 0) {
                ctx.moveTo(point.x, point.y);
            } else {
                ctx.lineTo(point.x, point.y);
            }
        });
        ctx.lineTo(points[points.length - 1].x, height - padding.bottom);
        ctx.lineTo(points[0].x, height - padding.bottom);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        ctx.strokeStyle = '#3370ff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        points.forEach((point, index) => {
            if (index === 0) {
                ctx.moveTo(point.x, point.y);
            } else {
                ctx.lineTo(point.x, point.y);
            }
        });
        ctx.stroke();

        if (points.length > 0) {
            const lastPoint = points[points.length - 1];
            ctx.fillStyle = '#3370ff';
            ctx.beginPath();
            ctx.arc(lastPoint.x, lastPoint.y, 3, 0, Math.PI * 2);
            ctx.fill();
        }

        ctx.fillStyle = '#86909c';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';

        const labelCount = Math.min(4, points.length);
        for (let i = 0; i < labelCount; i++) {
            const ratio = labelCount === 1 ? 0 : i / (labelCount - 1);
            const index = labelCount === 1 ? points.length - 1 : Math.round((points.length - 1) * ratio);
            const labelPoint = points[index];
            ctx.fillText(labelPoint.time, labelPoint.x, height - padding.bottom + 8);
        }

        this.chartCanvas = canvas;
    }

    updatePositions(positions) {
        const tbody = document.getElementById('positionsBody');
        
        if (positions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="empty-state">暂无持仓</td></tr>';
            return;
        }

        tbody.innerHTML = positions.map(pos => {
            const sideClass = pos.side === 'long' ? 'badge-long' : 'badge-short';
            const sideText = pos.side === 'long' ? '做多' : '做空';
            
            const currentPrice = pos.current_price !== null && pos.current_price !== undefined 
                ? `$${pos.current_price.toFixed(2)}` 
                : '-';
            
            let pnlDisplay = '-';
            let pnlClass = '';
            if (pos.pnl !== undefined && pos.pnl !== 0) {
                pnlClass = pos.pnl > 0 ? 'text-success' : 'text-danger';
                pnlDisplay = `${pos.pnl > 0 ? '+' : ''}$${pos.pnl.toFixed(2)}`;
            }
            
            return `
                <tr>
                    <td><strong>${pos.coin}</strong></td>
                    <td><span class="badge ${sideClass}">${sideText}</span></td>
                    <td>${pos.quantity.toFixed(4)}</td>
                    <td>$${pos.avg_price.toFixed(2)}</td>
                    <td>${currentPrice}</td>
                    <td>${pos.leverage}x</td>
                    <td class="${pnlClass}"><strong>${pnlDisplay}</strong></td>
                </tr>
            `;
        }).join('');
    }

    updateTrades(trades) {
        const tbody = document.getElementById('tradesBody');
        
        if (trades.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">暂无交易记录</td></tr>';
            return;
        }

        tbody.innerHTML = trades.map(trade => {
            const signalMap = {
                'buy_to_enter': { badge: 'badge-buy', text: '开多' },
                'sell_to_enter': { badge: 'badge-sell', text: '开空' },
                'close_position': { badge: 'badge-close', text: '平仓' }
            };
            const signal = signalMap[trade.signal] || { badge: '', text: trade.signal };
            const pnlClass = trade.pnl > 0 ? 'text-success' : trade.pnl < 0 ? 'text-danger' : '';

            return `
                <tr>
                    <td>${new Date(trade.timestamp.replace(' ', 'T') + 'Z').toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</td>
                    <td><strong>${trade.coin}</strong></td>
                    <td><span class="badge ${signal.badge}">${signal.text}</span></td>
                    <td>${trade.quantity.toFixed(4)}</td>
                    <td>$${trade.price.toFixed(2)}</td>
                    <td class="${pnlClass}">$${trade.pnl.toFixed(2)}</td>
                </tr>
            `;
        }).join('');
    }

    updateConversations(conversations) {
        const container = document.getElementById('conversationsBody');
        
        if (conversations.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无对话记录</div>';
            return;
        }

        container.innerHTML = conversations.map(conv => `
            <div class="conversation-item">
                <div class="conversation-time">${new Date(conv.timestamp.replace(' ', 'T') + 'Z').toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</div>
                <div class="conversation-content">${conv.ai_response}</div>
            </div>
        `).join('');
    }

    async loadMarketPrices() {
        try {
            const prices = await this.requestJson('/api/market/prices', { context: 'loadMarketPrices' });
            this.renderMarketPrices(prices);
        } catch (error) {
            console.error('Failed to load market prices:', error);
        }
    }

    renderMarketPrices(prices) {
        const container = document.getElementById('marketPrices');
        
        container.innerHTML = Object.entries(prices).map(([coin, data]) => {
            const changeClass = data.change_24h >= 0 ? 'positive' : 'negative';
            const changeIcon = data.change_24h >= 0 ? '▲' : '▼';
            
            return `
                <div class="price-item">
                    <div>
                        <div class="price-symbol">${coin}</div>
                        <div class="price-change ${changeClass}">${changeIcon} ${Math.abs(data.change_24h).toFixed(2)}%</div>
                    </div>
                    <div class="price-value">$${data.price.toFixed(2)}</div>
                </div>
            `;
        }).join('');
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
        document.getElementById(`${tabName}Tab`).classList.add('active');
    }

    showModal() {
        document.getElementById('addModelModal').classList.add('show');
    }

    hideModal() {
        document.getElementById('addModelModal').classList.remove('show');
    }

    async submitModel() {
        const data = {
            name: document.getElementById('modelName').value,
            api_key: document.getElementById('apiKey').value,
            api_url: document.getElementById('apiUrl').value,
            model_name: document.getElementById('modelIdentifier').value,
            initial_capital: parseFloat(document.getElementById('initialCapital').value)
        };

        if (!data.name || !data.api_key || !data.api_url || !data.model_name) {
            alert('请填写所有必填字段');
            return;
        }

        try {
            await this.requestJson('/api/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
                context: 'submitModel'
            });

            this.hideModal();
            this.loadModels();
            this.clearForm();
        } catch (error) {
            console.error('Failed to add model:', error);
            alert('添加模型失败');
        }
    }

    async deleteModel(modelId) {
        if (!confirm('确定要删除这个模型吗？')) return;

        try {
            await this.requestJson(`/api/models/${modelId}`, {
                method: 'DELETE',
                context: 'deleteModel'
            });

            if (this.currentModelId === modelId) {
                this.currentModelId = null;
            }
            this.loadModels();
        } catch (error) {
            console.error('Failed to delete model:', error);
        }
    }

    clearForm() {
        document.getElementById('modelName').value = '';
        document.getElementById('apiKey').value = '';
        document.getElementById('apiUrl').value = '';
        document.getElementById('modelIdentifier').value = '';
        document.getElementById('initialCapital').value = '100000';
    }

    async refresh() {
        await Promise.all([
            this.loadModels(),
            this.loadMarketPrices(),
            this.loadModelData()
        ]);
    }

    startRefreshCycles() {
        this.refreshIntervals.market = setInterval(() => {
            this.loadMarketPrices();
        }, 5000);

        this.refreshIntervals.portfolio = setInterval(() => {
            if (this.currentModelId) {
                this.loadModelData();
            }
        }, 10000);
    }

    stopRefreshCycles() {
        Object.values(this.refreshIntervals).forEach(interval => {
            if (interval) clearInterval(interval);
        });
    }
}

const app = new TradingApp();
