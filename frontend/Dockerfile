# 前端独立镜像：Node 构建 → nginx 托管（运行时零 Node 开销）
FROM node:20-alpine AS build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
