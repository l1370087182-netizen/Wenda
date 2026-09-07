<template>
  <div class="auth-page">
    <!-- 左侧品牌区 -->
    <div class="brand-panel">
      <div class="bp-inner">
        <div class="bp-logo">
          <div class="bp-mark">闻</div>
          <span>闻达 Wenda</span>
        </div>
        <h1 class="bp-headline">每天 3 分钟，<br />看懂六类世界</h1>
        <p class="bp-sub">多 Agent 采集分析 × 全库 RAG 检索，把信息噪音变成可执行的洞察。</p>
        <ul class="bp-features">
          <li><Icon name="zap" :size="16" /><b>智能日报</b><span>六类资讯自动采集、评分与交叉洞察</span></li>
          <li><Icon name="search" :size="16" /><b>深度问答</b><span>多轮对话，答案带编号溯源引用</span></li>
          <li><Icon name="mail" :size="16" /><b>订阅推送</b><span>每天一封邮件，只看你订阅的分类</span></li>
        </ul>
        <div class="bp-foot">科技 · 地缘 · 财经 · AI 技术 · AI 资讯 · GitHub 热点</div>
      </div>
    </div>

    <!-- 右侧表单区 -->
    <div class="form-panel">
      <div class="form-card">
        <div class="segmented full">
          <button v-for="t in TABS" :key="t.key" :class="{ on: tab === t.key }" @click="tab = t.key">
            {{ t.label }}
          </button>
        </div>

        <!-- 登录 -->
        <form v-if="tab === 'login'" autocomplete="on" @submit.prevent="doLogin">
          <div class="field">
            <label>邮箱 / 用户名</label>
            <input v-model.trim="login.email" class="input" placeholder="you@example.com" autocomplete="username" />
          </div>
          <div class="field">
            <label>密码</label>
            <div class="input-wrap">
              <input v-model="login.password" class="input" :type="showPw ? 'text' : 'password'"
                     placeholder="••••••••" autocomplete="current-password" />
              <button type="button" class="icon-btn toggle-eye" @click="showPw = !showPw">
                <Icon :name="showPw ? 'eye-off' : 'eye'" :size="16" />
              </button>
            </div>
          </div>
          <button class="btn btn-primary btn-block" type="submit" :disabled="busy">
            <span v-if="busy" class="spinner sm"></span><span v-else>登 录</span>
          </button>
        </form>

        <!-- 注册 -->
        <form v-else-if="tab === 'register'" autocomplete="off" @submit.prevent="doRegister">
          <div class="field">
            <label>邮箱</label>
            <input v-model.trim="reg.email" class="input" type="email" placeholder="you@example.com" />
          </div>
          <div class="field">
            <label>验证码</label>
            <div class="code-row">
              <input v-model.trim="reg.code" class="input" inputmode="numeric" maxlength="6" placeholder="6 位验证码" autocomplete="one-time-code" />
              <button type="button" class="btn btn-ghost" :disabled="cooldown > 0" @click="sendCode('register')">
                {{ cooldown > 0 ? `${cooldown}s` : '获取验证码' }}
              </button>
            </div>
          </div>
          <div class="field">
            <label>设置密码</label>
            <div class="input-wrap">
              <input v-model="reg.password" class="input" :type="showPw ? 'text' : 'password'"
                     placeholder="至少 8 位" autocomplete="new-password" />
              <button type="button" class="icon-btn toggle-eye" @click="showPw = !showPw">
                <Icon :name="showPw ? 'eye-off' : 'eye'" :size="16" />
              </button>
            </div>
          </div>
          <button class="btn btn-primary btn-block" type="submit" :disabled="busy">
            <span v-if="busy" class="spinner sm"></span><span v-else>注册并登录</span>
          </button>
        </form>

        <!-- 找回密码 -->
        <form v-else autocomplete="off" @submit.prevent="doReset">
          <div class="field">
            <label>邮箱</label>
            <input v-model.trim="reset.email" class="input" type="email" placeholder="you@example.com" />
          </div>
          <div class="field">
            <label>验证码</label>
            <div class="code-row">
              <input v-model.trim="reset.code" class="input" inputmode="numeric" maxlength="6" placeholder="6 位验证码" autocomplete="one-time-code" />
              <button type="button" class="btn btn-ghost" :disabled="cooldown > 0" @click="sendCode('reset')">
                {{ cooldown > 0 ? `${cooldown}s` : '获取验证码' }}
              </button>
            </div>
          </div>
          <div class="field">
            <label>新密码</label>
            <input v-model="reset.new_password" class="input" type="password" placeholder="至少 8 位" autocomplete="new-password" />
          </div>
          <button class="btn btn-primary btn-block" type="submit" :disabled="busy">
            <span v-if="busy" class="spinner sm"></span><span v-else>重置密码</span>
          </button>
        </form>

        <p class="switch-hint">
          {{ tab === 'login' ? '还没有账号？' : '已有账号？' }}
          <a @click="tab = tab === 'login' ? 'register' : 'login'">
            {{ tab === 'login' ? '立即注册' : '去登录' }}
          </a>
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import { store } from '../store'
import { toast } from '../composables/toast'
import Icon from '../components/Icon.vue'

const TABS = [
  { key: 'login', label: '登录' },
  { key: 'register', label: '注册' },
  { key: 'reset', label: '找回密码' },
]

const router = useRouter()
const tab = ref('login')
const busy = ref(false)
const showPw = ref(false)
const cooldown = ref(0)
const login = ref({ email: '', password: '' })
const reg = ref({ email: '', code: '', password: '' })
const reset = ref({ email: '', code: '', new_password: '' })

let timer = null
onUnmounted(() => clearInterval(timer))

async function sendCode(purpose) {
  const email = purpose === 'register' ? reg.value.email : reset.value.email
  if (!email) return toast('请先填写邮箱', 'warn')
  try {
    const r = await api.post('/auth/send-code', { email, purpose })
    toast(r.message || '验证码已发送', 'success')
    cooldown.value = 60
    timer = setInterval(() => { if (--cooldown.value <= 0) clearInterval(timer) }, 1000)
  } catch (e) { toast(e.message, 'error') }
}

// 登录/注册成功后拉取用户态，App 壳自动接管
async function authed() {
  store.user = await api.get('/auth/me')
  router.replace('/dashboard')
}

async function doLogin() {
  if (!login.value.email || !login.value.password) return toast('请填写完整', 'warn')
  busy.value = true
  try {
    await api.post('/auth/login', login.value)
    await authed()
  } catch (e) { toast(e.message, 'error') } finally { busy.value = false }
}

async function doRegister() {
  busy.value = true
  try {
    await api.post('/auth/register', reg.value)
    await authed()
  } catch (e) { toast(e.message, 'error') } finally { busy.value = false }
}

async function doReset() {
  busy.value = true
  try {
    const r = await api.post('/auth/reset-password', reset.value)
    toast(r.message || '密码已重置', 'success')
    tab.value = 'login'
  } catch (e) { toast(e.message, 'error') } finally { busy.value = false }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1fr 1fr;
}

/* ---------- 左侧品牌区 ---------- */
.brand-panel {
  position: relative; overflow: hidden;
  background: linear-gradient(160deg, #312e81 0%, #4f46e5 45%, #7c3aed 100%);
  color: #fff;
  display: flex; align-items: center;
  padding: 48px 56px;
}
/* 装饰网格与光晕 */
.brand-panel::before {
  content: ''; position: absolute; inset: 0;
  background-image: radial-gradient(rgba(255, 255, 255, 0.14) 1px, transparent 1px);
  background-size: 26px 26px;
  mask-image: radial-gradient(ellipse at 30% 20%, #000 30%, transparent 75%);
}
.brand-panel::after {
  content: ''; position: absolute; width: 420px; height: 420px; border-radius: 50%;
  right: -160px; bottom: -160px;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.12), transparent 65%);
}
.bp-inner { position: relative; z-index: 1; max-width: 440px; }

.bp-logo { display: flex; align-items: center; gap: 12px; font-size: 17px; font-weight: 700; margin-bottom: 44px; }
.bp-mark {
  width: 42px; height: 42px; border-radius: 12px;
  background: rgba(255, 255, 255, 0.16); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; font-weight: 700;
  border: 1px solid rgba(255, 255, 255, 0.25);
}
.bp-headline { font-size: 38px; font-weight: 800; line-height: 1.28; letter-spacing: -0.02em; margin-bottom: 14px; }
.bp-sub { font-size: 15px; opacity: 0.85; line-height: 1.75; margin: 0 0 36px; }

.bp-features { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 18px; }
.bp-features li { display: grid; grid-template-columns: 22px 68px 1fr; align-items: center; gap: 10px; font-size: 13.5px; }
.bp-features svg { opacity: 0.9; }
.bp-features b { font-size: 14px; }
.bp-features span { opacity: 0.75; }
.bp-foot { margin-top: 44px; font-size: 12px; letter-spacing: 0.12em; opacity: 0.55; }

/* ---------- 右侧表单区 ---------- */
.form-panel {
  display: flex; align-items: center; justify-content: center;
  padding: 40px 24px;
  background: var(--bg);
}
.form-card {
  width: 100%; max-width: 400px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 20px;
  box-shadow: var(--shadow-lg);
  padding: 30px 30px 24px;
}

.segmented.full { display: flex; width: 100%; margin-bottom: 24px; }
.segmented.full button { flex: 1; height: 34px; }

.code-row { display: flex; gap: 8px; }
.code-row .input { flex: 1; font-family: var(--font-num); letter-spacing: 0.1em; }

.switch-hint { text-align: center; font-size: 13px; color: var(--ink-3); margin: 18px 0 0; }
.switch-hint a { color: var(--brand); font-weight: 600; cursor: pointer; }
.switch-hint a:hover { color: var(--brand-2); }

.spinner.sm { width: 16px; height: 16px; border-width: 2px; border-color: rgba(255, 255, 255, 0.4); border-top-color: #fff; }

@media (max-width: 900px) {
  .auth-page { grid-template-columns: 1fr; }
  .brand-panel { display: none; }
}
</style>
