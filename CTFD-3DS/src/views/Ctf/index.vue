<template>
  <div class="ctf-container">
    <!-- 3D 背景层 -->
    <div class="playground" id="ctf"></div>
    
    <!-- UI 遮罩层：大屏左侧排行榜 -->
    <div class="ui-panel panel-left">
      <div class="panel-title">🏆 实时积分榜</div>
      <ul class="rank-list">
        <li v-for="(team, index) in rankData" :key="index" class="rank-item">
          <span class="rank-num">{{ index + 1 }}</span>
          <span class="team-name">{{ team.name }}</span>
          <span class="team-score">{{ team.score }}</span>
        </li>
      </ul>
    </div>

    <!-- UI 遮罩层：大屏右侧预测图表 -->
    <div class="ui-panel panel-right">
      <div class="panel-title">🔮 AI 态势预测中心</div>
      
      <!-- 科幻风刷新控制台 -->
      <div class="control-bar">
        <label class="control-item">
          <input type="checkbox" v-model="autoRefresh" @change="toggleAutoRefresh" />
          <span class="toggle-text">自动同步 AI 态势</span>
        </label>
        <label class="control-item" v-if="autoRefresh">
          频率:
          <!-- 【修复】：明确 $event 类型或不传参直接调用 -->
          <select v-model="refreshInterval" @change="updateInterval($event)" class="cyber-select">
            <option :value="10000">10 秒</option>
            <option :value="30000">30 秒</option>
            <option :value="60000">1 分钟</option>
            <option :value="300000">5 分钟</option>
          </select>
        </label>
      </div>

      <div id="predict-chart" style="width: 100%; height: 260px;"></div>
      
      <!-- 大模型赛况解说播报区 -->
      <div class="ai-commentary-box">
        <div class="ai-header">🤖 战况智能解说分析：</div>
        <div class="ai-text">{{ aiCommentary }}</div>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { Component, Vue } from 'vue-property-decorator';
import axios from "axios";
import * as echarts from 'echarts';
import { PlaygroundCTF, CTFAssetsLoader, TargetCTF, TeamCTF, random } from './index'

// 【修复】：为排行榜数据增加明确的 TS 接口
interface RankItem {
  name: string;
  score: number;
}

@Component
export default class CTF extends Vue {
    // 【修复】：显式指定数组类型
    rankData: RankItem[] = [];
    aiCommentary: string = "⏳ 正在连线后台 AI 分析中心...";
    
    autoRefresh: boolean = true;
    refreshInterval: number = 30000;
    timerId: any = null;
    attackTimer: any = null;

    playgroundCTF: any = null;
    assets: any = null;
    existingTargetNames: Set<string> = new Set();
    existingTeamNames: Set<string> = new Set();
    teamsInst: any[] = [];
    targetsInst: any[] = [];

    mounted() {
        const savedRefresh = localStorage.getItem('ctf_autoRefresh');
        if (savedRefresh !== null) this.autoRefresh = savedRefresh === 'true';
        const savedInterval = localStorage.getItem('ctf_refreshInterval');
        if (savedInterval !== null) this.refreshInterval = Number(savedInterval);
        
        this.init();
    }

    beforeDestroy() {
        this.clearTimer();
        if (this.attackTimer) clearTimeout(this.attackTimer);
        document.querySelectorAll('.panels').forEach(el => el.remove());
    }

    toggleAutoRefresh() {
        localStorage.setItem('ctf_autoRefresh', String(this.autoRefresh));
        if (this.autoRefresh) this.startTimer();
        else this.clearTimer();
    }

    updateInterval(event?: any) {
        localStorage.setItem('ctf_refreshInterval', String(this.refreshInterval));
        if (this.autoRefresh) {
            this.clearTimer();
            this.startTimer();
        }
    }

    clearTimer() {
        if (this.timerId) {
            clearInterval(this.timerId);
            this.timerId = null;
        }
    }

    startTimer() {
        this.timerId = setInterval(() => {
            this.fetchDataAndRender(false); 
        }, Number(this.refreshInterval));
    }

    async fetchDataAndRender(isInitial: boolean) {
      try {
        const apiHost = window.location.hostname;
        const response = await axios.get(`http://${apiHost}:8000/api/v1/plugins/predictor/trends`, {
            timeout: 10000 
        });

        if (!response.data || !response.data.success) {
            this.aiCommentary = "⚠️ AI 分析中心返回异常，请联系管理员检查 CTFd 后台日志。";
            return null;
        }
        
        const realData = response.data.data;
        const teamList: string[] = realData.teams || [];

        const latestHistory = realData.history[realData.history.length - 1];
        if (latestHistory) {
          // 【修复】：显式声明映射出的对象符合 RankItem 接口
          this.rankData = teamList.map((name: string): RankItem => ({
            name: name,
            score: latestHistory[name] || 0
          })).sort((a: RankItem, b: RankItem) => b.score - a.score);
        }
        
        this.renderChart(realData.history, realData.predictions, teamList);
        
        if (realData.commentary) {
            this.aiCommentary = realData.commentary;
        } else {
            this.aiCommentary = "暂无最新战报，等待底层的影子进程生成...";
        }

        if (!isInitial && this.playgroundCTF && this.assets) {
            const newTargets = (realData.targets || []).map((t: any) => ({
                name: `${t.name} | Top: ${t.top_team || '-'}`,
                score: t.score
            }));
            
            const targetsToAdd: any[] = [];
            newTargets.forEach((t: any) => {
                if (!this.existingTargetNames.has(t.name)) {
                    this.existingTargetNames.add(t.name);
                    const buildingModel = this.assets.buildings[random(0, this.assets.buildings.length - 1)];
                    const targetInst = new TargetCTF(buildingModel, t.name, t.score);
                    targetsToAdd.push(targetInst);
                    this.targetsInst.push(targetInst);
                }
            });

            const teamsToAdd: any[] = [];
            teamList.forEach((tName: string) => {
                if (!this.existingTeamNames.has(tName)) {
                    this.existingTeamNames.add(tName);
                    const teamModel = this.assets.aerobat;
                    const teamInst = new TeamCTF(teamModel as any, tName);
                    teamsToAdd.push(teamInst);
                    this.teamsInst.push(teamInst);
                }
            });

            if (targetsToAdd.length > 0) this.playgroundCTF.setTargets(this.targetsInst);
            if (teamsToAdd.length > 0) this.playgroundCTF.setTeams(this.teamsInst);
        }

        return realData;
      } catch (e: any) {
        console.error("数据拉取失败:", e);
        if (e.code === 'ECONNABORTED') {
            this.aiCommentary = "🚨 请求后端 API 超时！大模型分析进程可能卡死。";
        } else {
            this.aiCommentary = "🚨 网络连线失败，请确认后端 CTFd 8000 端口及 AI 插件是否存活。";
        }
        return null;
      }
    }

    async init() {
      this.assets = await CTFAssetsLoader.load();
      
      const realData = await this.fetchDataAndRender(true);
      const teamList = realData ? (realData.teams || []) : [];
      const targetData = { 
          data: (realData ? (realData.targets || []) : []).map((target: any) => ({
            name: `${target.name} | Top: ${target.top_team || '-'}`,
            score: target.score 
          }))
      }

      this.playgroundCTF = new PlaygroundCTF((document.querySelector('#ctf') as HTMLElement), this.assets);
      
      this.targetsInst = targetData.data.map((item:any) => {
        this.existingTargetNames.add(item.name);
        const buildingModel = this.assets.buildings[random(0, this.assets.buildings.length - 1)];
        return new TargetCTF(buildingModel, item.name, item.score);
      });
      
      this.teamsInst = teamList.map((tName:string) => {
        this.existingTeamNames.add(tName);
        const teamModel = this.assets.aerobat;
        return new TeamCTF(teamModel as any, tName);
      });
      
      if(this.targetsInst.length > 0) this.playgroundCTF.setTargets(this.targetsInst);
      if(this.teamsInst.length > 0) this.playgroundCTF.setTeams(this.teamsInst);

      const randomAttack = () => {
        if (!this.teamsInst.length || !this.targetsInst.length) return;
        const team = this.teamsInst[random(0, this.teamsInst.length - 1)];
        const target = this.targetsInst[random(0, this.targetsInst.length - 1)];
        const isSuccess = Math.random() > 0.5;
        team.toAttack(target, isSuccess);
        
        this.attackTimer = setTimeout(randomAttack, Math.random() * 10000);
      };
      this.attackTimer = setTimeout(randomAttack, 5000);

      if (this.autoRefresh) {
        this.startTimer();
      }
    }

    renderChart(history: any[], predictions: any[], teams: string[]) {
      const chartDom = document.getElementById('predict-chart');
      if (!chartDom) return;
      const myChart = echarts.init(chartDom);

      const timeAxis = [...history, ...predictions].map(item => { 
        const date = new Date(item.time * 1000);
        return `${date.getHours()}:${date.getMinutes().toString().padStart(2, '0')}`;
      });

      const seriesData = teams.map(team => {
        const data = [...history, ...predictions].map(item => item[team] || 0);
        return {
          name: team,
          type: 'line',
          smooth: true,
          data: data,
          markArea: {
            data: [[{ xAxis: history.length - 1 }, { xAxis: timeAxis.length - 1 }]],
            itemStyle: { color: 'rgba(255, 173, 51, 0.1)' }
          }
        };
      });

      const option = {
        tooltip: { trigger: 'axis' },
        legend: { data: teams, textStyle: { color: '#fff' }, type: 'scroll' },
        xAxis: { type: 'category', data: timeAxis, axisLabel: { color: '#fff' } },
        yAxis: { type: 'value', axisLabel: { color: '#fff' }, splitLine: { lineStyle: { color: '#333' } } },
        series: seriesData
      };
      myChart.setOption(option, true);
    }
}
</script>

<style>
.panels {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 5;
}
</style>

<style scoped>
.ctf-container {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}

.playground {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
}

.ui-panel {
  position: absolute;
  top: 80px;
  z-index: 10;
  width: 350px;
  background: rgba(10, 25, 47, 0.8);
  border: 1px solid rgba(0, 255, 255, 0.3);
  border-radius: 10px;
  padding: 20px;
  color: #fff;
  box-shadow: 0 0 20px rgba(0, 255, 255, 0.2);
  backdrop-filter: blur(5px);
}

.panel-left { left: 30px; }
.panel-right { right: 30px; width: 450px; }

.panel-title {
  font-size: 20px;
  font-weight: bold;
  margin-bottom: 15px;
  text-align: center;
  color: #00ffff;
  text-shadow: 0 0 10px #00ffff;
}

.rank-list { list-style: none; padding: 0; margin: 0; }
.rank-item {
  display: flex;
  justify-content: space-between;
  padding: 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-size: 16px;
}
.rank-num {
  color: #ffaa00;
  font-weight: bold;
  width: 30px;
}
.team-name { flex: 1; }
.team-score { color: #00ffaa; font-weight: bold; }

.ai-commentary-box {
  margin-top: 15px;
  padding: 15px;
  background: rgba(0, 50, 100, 0.4);
  border-left: 4px solid #00aaff;
  border-radius: 4px;
  font-size: 14px;
  line-height: 1.6;
}
.ai-header {
  color: #00aaff;
  font-weight: bold;
  margin-bottom: 8px;
  font-size: 15px;
}
.ai-text {
  color: #e0f7fa;
  text-shadow: 0 0 2px rgba(224, 247, 250, 0.5);
  white-space: pre-wrap;
}

.control-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  padding: 5px 10px;
  background: rgba(0, 50, 100, 0.3);
  border-radius: 5px;
  border: 1px solid rgba(0, 255, 255, 0.2);
}

.control-item {
  display: flex;
  align-items: center;
  font-size: 13px;
  color: #00ffff;
  cursor: pointer;
}

.control-item input[type="checkbox"] {
  margin-right: 8px;
  cursor: pointer;
}

.cyber-select {
  margin-left: 8px;
  background: rgba(10, 25, 47, 0.9);
  color: #00ffff;
  border: 1px solid #00aaff;
  padding: 2px 5px;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}

.cyber-select option {
  background: #0a192f;
  color: #00ffff;
}
</style>