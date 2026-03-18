FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_BASE_URL=http://localhost:3000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
RUN addgroup -S web && adduser -S web -G web
COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chown -R web:web /usr/share/nginx/html /var/cache/nginx /var/run /var/log/nginx
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
