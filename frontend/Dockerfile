FROM node:20-alpine

WORKDIR /app

# Copies the package manifest first because Docker can reuse the dependency layer when only source files change.
COPY package.json ./

RUN npm install

# Copies the application source because the Vite dev server needs the full frontend workspace at runtime.
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
