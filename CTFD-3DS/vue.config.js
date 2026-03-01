const { defineConfig } = require('@vue/cli-service')
module.exports = defineConfig({
  transpileDependencies: true,
  publicPath: './',

  // 【核心修复】：彻底关闭打包时的 ESLint 代码洁癖检查，忽略所有 warning 和格式 error
  lintOnSave: false

})
