import uvicorn

if __name__ == '__main__':
    uvicorn.run('image_to_3d_print.api.app:create_app', factory=True, host='127.0.0.1', port=8000)
