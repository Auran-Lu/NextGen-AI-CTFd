# ==========================================
# 阶段 1：编译构建阶段 (使用 Node 环境打包 Vue/Three.js)
# ==========================================
FROM node:18-alpine AS builder

WORKDIR /app

# 复制包管理文件并使用阿里镜像安装依赖
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com/ && npm install

# 复制所有源代码并打包 (生成 dist 目录)
COPY . .
RUN npm run build

# ==========================================
# 阶段 2：生产运行阶段 (使用 Nginx 提供极速静态托管)
# ==========================================
FROM nginx:alpine

# 将构建好的静态文件复制到 Nginx 的默认网页目录
COPY --from=builder /app/dist /usr/share/nginx/html

# 暴露 80 端口
EXPOSE 80

# 启动 Nginx
CMD ["nginx", "-g", "daemon off;"]