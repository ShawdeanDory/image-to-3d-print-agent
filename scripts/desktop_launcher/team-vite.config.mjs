// 只运行既有dist，不加载开发插件；不增加业务接口或公网监听。
export default {
  preview: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': { target: process.env.I3D_API_TARGET || 'http://127.0.0.1:9000', changeOrigin: false } },
  },
};
