const API_BASE_URL = 'https://carverjobs-mono-production.up.railway.app/api/v1';

export class ApiError extends Error {
  constructor(message: string, public status: number, public data: any) {
    super(message);
  }
}

interface ApiRequestOptions extends RequestInit {
  headers?: Record<string, string>;
}

async function apiRequest(endpoint: string, options: ApiRequestOptions = {}): Promise<any> {
  const url = `${API_BASE_URL}${endpoint}`;
  const token = localStorage.getItem('auth_token');
  
  const defaultOptions: ApiRequestOptions = {
    headers: {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
    },
  };

  const mergedOptions: ApiRequestOptions = {
    ...defaultOptions,
    ...options,
    headers: {
      ...defaultOptions.headers,
      ...options.headers,
    },
  };

  try {
    const response = await fetch(url, mergedOptions);
    
    // Handle cases where response is not JSON
    let data;
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      data = await response.json();
    } else {
      data = { message: await response.text() };
    }

    if (!response.ok) {
      throw new ApiError(data.message || `Request failed with status ${response.status}`, response.status, data);
    }

    return data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    
    // Network or other errors
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new ApiError('Network error - please check your connection', 0, null);
    }
    
    throw new ApiError('An unexpected error occurred', 0, null);
  }
}

interface RegisterData {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
}

interface LoginCredentials {
  email: string;
  password: string;
}

interface JobFilters {
  type?: string;
  location?: string;
  company?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  // Auth endpoints
  async register(userData: RegisterData) {
    return apiRequest('/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    });
  },

  async login(credentials: LoginCredentials) {
    return apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
  },

  async getProfile() {
    return apiRequest('/auth/profile');
  },

  // Job endpoints
  async getJobs(filters: JobFilters = {}) {
    const params = new URLSearchParams();
    
    if (filters.type) params.append('type', filters.type);
    if (filters.location) params.append('location', filters.location);
    if (filters.company) params.append('company', filters.company);
    if (filters.limit) params.append('limit', filters.limit.toString());
    if (filters.offset) params.append('offset', filters.offset.toString());

    const query = params.toString();
    const endpoint = query ? `/jobs?${query}` : '/jobs';
    
    const response = await apiRequest(endpoint);
    
    // Handle case where backend returns error message instead of expected format
    if (response && typeof response === 'object' && 'message' in response && !('jobs' in response)) {
      throw new ApiError(response.message, 500, response);
    }
    
    // Ensure response has expected structure
    return {
      jobs: response?.jobs || [],
      total: response?.total || 0,
      page: response?.page || 1,
      limit: response?.limit || 10
    };
  },

  async getJobById(id: string) {
    return apiRequest(`/jobs/${id}`);
  },

  // Health check
  async healthCheck() {
    const response = await fetch('https://carverjobs-mono-production.up.railway.app/health');
    return response.json();
  },
}; 