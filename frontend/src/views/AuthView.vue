<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <h2 style="text-align:center;margin-bottom:20px">📰 六类资讯日报</h2>
      <el-tabs v-model="tab">
        <!-- 登录 -->
        <el-tab-pane label="登录" name="login">
          <el-form @submit.prevent="doLogin">
            <el-form-item><el-input v-model="login.email" placeholder="邮箱 / 用户名" size="large" /></el-form-item>
            <el-form-item><el-input v-model="login.password" type="password" placeholder="密码" show-password size="large" /></el-form-item>
            <el-button type="primary" size="large" style="width:100%" native-type="submit" :loading="busy">登录</el-button>
          </el-form>
        </el-tab-pane>

        <!-- 注册 -->
        <el-tab-pane label="注册" name="register">
          <el-form @submit.prevent="doRegister">
            <el-form-item><el-input v-model="reg.email" placeholder="邮箱" size="large" /></el-form-item>
            <el-form-item>
              <div class="code-row">
                <el-input v-model="reg.code" placeholder="6 位验证码" maxlength="6" size="large" />
                <el-button :disabled="cooldown > 0" @click="sendCode('register')">
                  {{ cooldown > 0 ? `${cooldown}s` : '发送验证码' }}
                </el-button>
              </div>
            </el-form-item>
            <el-form-item><el-input v-model="reg.password" type="password" placeholder="密码（至少 8 位）" show-password size="large" /></el-form-item>
            <el-button type="primary" size="large" style="width:100%" native-type="submit" :loading="busy">注册并登录</el-button>
          </el-form>
        </el-tab-pane>

        <!-- 找回密码 -->
        <el-tab-pane label="找回密码" name="reset">
          <el-form @submit.prevent="doReset">
            <el-form-item><el-input v-model="reset.email" placeholder="邮箱" size="large" /></el-form-item>
            <el-form-item>
              <div class="code-row">
                <el-input v-model="reset.code" placeholder="6 位验证码" maxlength="6" size="large" />
                <el-button :disabled="cooldown > 0" @click="sendCode('reset')">
                  {{ cooldown > 0 ? `${cooldown}s` : '发送验证码' }}
                </el-button>
              </div>
            </el-form-item>
            <el-form-item><el-input v-model="reset.new_password" type="password" placeholder="新密码（至少 8 位）" show-password size="large" /></el-form-item>
            <el-button type="primary" size="large" style="width:100%" native-type="submit" :loading="busy">重置密码</el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()
const tab = ref('login')
const busy = ref(false)
const cooldown = ref(0)
const login = ref({ email: '', password: '' })
const reg = ref({ email: '', code: '', password: '' })
const reset = ref({ email: '', code: '', new_password: '' })

async function sendCode(purpose) {
  const email = purpose === 'register' ? reg.value.email : reset.value.email
  if (!email) return ElMessage.warning('请先填写邮箱')
  try {
    const r = await api.post('/auth/send-code', { email, purpose })
    ElMessage.success(r.message)
    cooldown.value = 60
    const t = setInterval(() => { if (--cooldown.value <= 0) clearInterval(t) }, 1000)
  } catch (e) { ElMessage.error(e.message) }
}

async function doLogin() {
  busy.value = true
  try {
    await api.post('/auth/login', login.value)
    location.reload()  // 重新走 App.vue 的登录态检查
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}

async function doRegister() {
  busy.value = true
  try {
    await api.post('/auth/register', reg.value)
    location.reload()
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}

async function doReset() {
  busy.value = true
  try {
    const r = await api.post('/auth/reset-password', reset.value)
    ElMessage.success(r.message)
    tab.value = 'login'
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}
</script>

<style scoped>
.auth-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
.auth-card { width: 400px; }
.code-row { display: flex; gap: 8px; width: 100%; }
.code-row .el-input { flex: 1; }
</style>
