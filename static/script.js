document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('location-form');
    const submitBtn = document.getElementById('submit-btn');
    const loadingDiv = document.getElementById('loading');
    const resultsDiv = document.getElementById('results');
    const analysisOutput = document.getElementById('analysis-output');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Hide previous results and show loading indicator
        resultsDiv.classList.add('hidden');
        loadingDiv.classList.remove('hidden');
        submitBtn.disabled = true;
        submitBtn.textContent = '分析中...';

        const formData = new FormData(form);
        const data = {
            work_address1: formData.get('work_address1'),
            work_address2: formData.get('work_address2'),
            budget_range: formData.get('budget_range') || '不限',
            preferences: formData.get('preferences') || ''
        };

        try {
            const response = await fetch('/find_rental_location', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '分析请求失败');
            }

            const result = await response.json();

            if (result.error) {
                analysisOutput.innerHTML = `<p><strong>错误:</strong> ${result.error}</p><pre>${JSON.stringify(result.debug_info, null, 2)}</pre>`;
            } else {
                // Use marked.js to render the markdown response
                analysisOutput.innerHTML = marked.parse(result.rental_location_analysis);
            }
            
            resultsDiv.classList.remove('hidden');

        } catch (error) {
            analysisOutput.innerHTML = `<p style="color: red;"><strong>请求出错:</strong> ${error.message}</p>`;
            resultsDiv.classList.remove('hidden');
        } finally {
            // Hide loading indicator and re-enable button
            loadingDiv.classList.add('hidden');
            submitBtn.disabled = false;
            submitBtn.textContent = '开始分析';
        }
    });
});
