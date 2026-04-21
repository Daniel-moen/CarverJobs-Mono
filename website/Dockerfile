FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_BASE_URL=http://localhost:3001
ARG VITE_SITE_LAUNCHED=true
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_SITE_LAUNCHED=$VITE_SITE_LAUNCHED
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
RUN apk add --no-cache gettext \
    && addgroup -S web && adduser -S web -G web
ENV PORT=8080
ENV API_URL=http://localhost:3001
COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
# Safety net: guarantee .well-known is present even if the build step skipped dotfiles.
COPY --from=build /app/public/.well-known /usr/share/nginx/html/.well-known
# Pre-rendered markdown served via Accept: text/markdown content negotiation.
COPY --from=build /app/public/_md /usr/share/nginx/html/_md
RUN chown -R web:web /usr/share/nginx/html /var/cache/nginx /var/run /var/log/nginx
EXPOSE 8080
CMD ["/bin/sh", "-c", "envsubst '$PORT $API_URL' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf && exec nginx -g 'daemon off;'"]
