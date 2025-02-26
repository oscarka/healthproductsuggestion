Page({
    data: {
        fileList: [],
        showResult: false,
        result: null,
        resultDesc: '',
        gridConfig: {
            column: 1,
            width: 240,
            height: 240
        },
        apiBaseUrl: 'http://localhost:5001'  // 本地开发时的地址
        // apiBaseUrl: 'https://your-railway-app.railway.app'  // Railway部署后的地址
    },

    handleSuccess(e) {
        const { fileList } = e.detail;

        // 获取文件路径
        const filePath = fileList[0].url;

        // 上传到服务器
        wx.uploadFile({
            url: `${this.data.apiBaseUrl}/api/upload`,
            filePath: filePath,
            name: 'image',
            success: (res) => {
                const result = JSON.parse(res.data);
                if (result.code === 200) {
                    this.setData({
                        result: result.data,
                        showResult: true
                    });
                } else {
                    wx.showToast({
                        title: result.message,
                        icon: 'none'
                    });
                }
            },
            fail: (err) => {
                wx.showToast({
                    title: '上传失败',
                    icon: 'error'
                });
            }
        });
    },

    handleBack() {
        this.setData({
            showResult: false,
            result: null,
            fileList: []
        });
    }
}); 