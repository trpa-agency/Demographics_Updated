import pandas as pd
import numpy as np
import requests
import pyodbc
import arcpy
from arcgis.features import FeatureLayer

#Helper function that is used to concatenate census data return
def create_or_append_df(df, summary_df):
    if df.empty:
        df = summary_df.copy()
    else:
        df = pd.concat([df, summary_df])
    return df

#This gets the result of the get request and does some data wrangling to make it fit our structure
def get_request_census(request_url, sample_level, geo_name):
    response = requests.get(request_url)
    print(response.status_code)
    df = pd.DataFrame(response.json())
    #The json returns column names in the first row
    df.columns = df.iloc[0]
    df = df[1:]
    df['sample_level']=sample_level
    df['Geo_Name']=geo_name
    #Might as well add counties and states at this stage
    return df

def get_jobs_data(year, census_geom_year, variable, variablename, census_api_key, tahoe_geometry, variable_category):
    base_url = 'https://api.census.gov/data/'
    df_total=pd.DataFrame()
    #Formatting to match html get request
    #get the zipcodes for inclusion from tahoe_geometry
    zipcodes = tahoe_geometry['TRPAID'].loc[(tahoe_geometry['YEAR']==census_geom_year)&(tahoe_geometry['GEOGRAPHY']=='ZIP CODE')].str[:-4]
    print(zipcodes)
    
    for zipcode in zipcodes:
        #print(f'{base_url}/{year}/cbp?get={variable}&for={geometry_return}:*&in=state:{state}%20county:{county}{geometry_level}&key={census_api_key}')
        request_url = f'{base_url}{year}/cbp?get=GEO_ID,{variable}&for=zip%20code:{zipcode}&key={census_api_key}'
        print (request_url)
        response = requests.get(request_url)
        
        df = pd.DataFrame(response.json())
        #The json returns column names in the first row
        df.columns = df.iloc[0]
        df = df[1:]
        #Might as well add counties and states at this stage
        if df_total.empty:
            df_total=df
        else:
            df_total=pd.concat([df_total, df])

    #Figure out exactly what variable we want here
    #Add something here to handle margin of error
    df_total['variable_code']=variable
    df_total['variable_name']=variablename
    df_total['variable_category']= variable_category
    df_total['year_sample']=year
    df_total['sample_level']='ZIP CODE'
    df_total['dataset']= 'cbp'
    df_total['census_geom_year'] = census_geom_year
    df_total['GEO_ID'] = df_total['GEO_ID'].str.split('US').str[1]
    df_total['TRPAID'] = df_total['GEO_ID']+df_total['census_geom_year'].astype(str)
    df_total.columns.values[1] = 'value'
    df_total['value'] = df_total['value'].astype(float)
    df_total.insert(2, 'MarginOfError', np.NaN)
    return df_total


def get_variable_data(year, dataset, geometry_return, variable, variablename, census_api_key, census_geom_year, tahoe_geometry, variable_category):
    #Returns all data for a given dataset for Washoe, El Dorado, Carson City, Douglas, Placer Counties
    #Need to make five seperate api calls because of the geometry structure
    county_states ={
        '06': ['017','061'],
        '32': ['005', '031']
    }
    base_url = 'https://api.census.gov/data'
    df_total=pd.DataFrame()
    #Formatting to match html get request
    geometry_return=geometry_return.replace(" ", "%20")
    #This adds tract level to make block groups or blocks get request valid
    if geometry_return == 'tract':
        geometry_level = ''
    else:
        geometry_level='%20tract:*'
    if 'acs/acs5' in dataset:
        variable= variable +'E,'+variable + 'M'

    
    for state in county_states:
        for county in county_states[state]:
            print(f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for={geometry_return}:*&in=state:{state}%20county:{county}{geometry_level}&key={census_api_key}')
            request_url = f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for={geometry_return}:*&in=state:{state}%20county:{county}{geometry_level}&key={census_api_key}'
            response = requests.get(request_url)
            
            df = pd.DataFrame(response.json())
            #The json returns column names in the first row
            df.columns = df.iloc[0]
            df = df[1:]
            #Might as well add counties and states at this stage
            if df_total.empty:
                df_total=df
            else:
                df_total=pd.concat([df_total, df])
    #Figure out exactly what variable we want here
    #Add something here to handle margin of error
    df_total['variable_code']=variable
    df_total['variable_name']=variablename
    df_total['variable_category']= variable_category
    df_total['year_sample']=year
    df_total['sample_level']=geometry_return.replace("%20", " ")
    df_total['dataset']= dataset
    df_total['census_geom_year'] = census_geom_year
    df_total['GEO_ID'] = df_total['GEO_ID'].str.split('US').str[1]
    df_total['TRPAID'] = df_total['GEO_ID']+df_total['census_geom_year'].astype(str)
    df_total.columns.values[1] = 'value'
    df_total['value'] = df_total['value'].astype(float)
    if 'acs/acs5' in dataset:
        df_total.columns.values[2]='MarginOfError'
        df_total['variable_code'] = df_total['variable_code'].str.split(',').str[0]
    else:
        df_total.insert(2, 'MarginOfError', np.NaN)
    if geometry_return == 'tract':
        tract_col_loc = df_total.columns.get_loc('tract')
        df_total.insert(tract_col_loc, 'block group', np.NaN)

    #filter to just the tahoe parcels
    df_total = df_total[df_total['TRPAID'].isin(tahoe_geometry['TRPAID'])]
    df_total =  pd.merge(df_total, tahoe_geometry[['TRPAID', 'NEIGHBORHOOD']], on='TRPAID', how= 'left')
    
    return df_total

def get_non_tahoe_data(year,dataset, variable, variablename, census_api_key, census_geom_year, variable_category):
    base_url = 'https://api.census.gov/data'
    df_total=pd.DataFrame()
    county_states ={
        '06': ['017','061'],
        '32': ['005', '031', '510']
    }
    state_names={
        '06':'CA',
        '32':'NV'
    }
    county_names={
        '017':'El Dorado County',
        '061':'Placer County',
        '005':'Douglas County',
        '031':'Washoe County',
        '510':'Carson City County'
    }
    #Need to update this so that it handles the different years - are 2010 and 2020 the same?
    urban_centers = {
        'Reno-Sparks MSA':'39900',
        'Sacramento MSA': '40900',   
    }
    combined_metro_areas={
        'Sanfranciso CMSA': '488'
    }
    urban_centers_2000 = {
        'Reno-Sparks MSA':'6720',
        'Sacramento MSA': '6922',   
    }
    combined_metro_areas_2000={
        'Sanfranciso CMSA': '7362'
    }
    if year!="2000":
        for urban_center in urban_centers:
            urban_center_code = urban_centers[urban_center]
            print(f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=metropolitan%20statistical%20area/micropolitan%20statistical%20area:{urban_center_code}&key={census_api_key}')
            request_url = f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=metropolitan%20statistical%20area/micropolitan%20statistical%20area:{urban_center_code}&key={census_api_key}'            
            df = get_request_census(request_url,'MSA', urban_center)
            df_total = create_or_append_df(df_total, df)    
        for cma in combined_metro_areas:
            cma_code = combined_metro_areas[cma]
            print(f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=combined%20statistical%20area:{cma_code}&key={census_api_key}')
            request_url = f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=combined%20statistical%20area:{cma_code}&key={census_api_key}'
            df = get_request_census(request_url, 'MSA', cma)
            df_total = create_or_append_df(df_total, df)
    # for urban_center in urban_centers_2000:
    #         urban_center_code = urban_centers_2000[urban_center]
    #         statistical_region_url = f'metropolitan%20statistical%20area/micropolitan%20statistical%20area'
    #         print(f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for={statistical_region_url}:{urban_center_code}&key={census_api_key}')
    #         request_url= f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for={statistical_region_url}:{urban_center_code}&key={census_api_key}'
    #         df = get_request_census(request_url,'MSA',urban_center)
    #         df_total = create_or_append_df(df_total,df)
        
    for state in county_states:
        for county in county_states[state]:
            #https://api.census.gov/data/2010/dec/sf1?get=GEO_ID,P001001&for=county:017&in=state:06&key=9a73d08c296b844e58f1c70bd19c831826da5cbf
            print(f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=county:{county}&in=state:{state}&key={census_api_key}')
            request_url = f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=county:{county}&in=state:{state}&key={census_api_key}'
            countyname = county_names[county]
            df = get_request_census(request_url, 'County', countyname)
            df_total = create_or_append_df(df_total, df)
    for state in county_states:
        #https://api.census.gov/data/2010/dec/sf1?get=GEO_ID,P001001&for=county:017&in=state:06&key=9a73d08c296b844e58f1c70bd19c831826da5cbf
        print(f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=state:{state}&key={census_api_key}')
        request_url = f'{base_url}/{year}/{dataset}?get=GEO_ID,{variable}&for=state:{state}&key={census_api_key}'
        geoname = state_names[state]
        df = get_request_census(request_url,'State', geoname)
        df_total = create_or_append_df(df_total, df)
        
    #Figure out exactly what variable we want here
    df_total['variable_code']=variable
    df_total['variable_name']=variablename
    df_total['variable_category']= variable_category
    df_total['year_sample']=year
    df_total['dataset']= dataset
    df_total['census_geom_year'] = census_geom_year
    df_total['GEO_ID'] = df_total['GEO_ID'].str.split('US').str[1]
    df_total['GEO_CODE'] = df_total['GEO_ID']+df_total['census_geom_year'].astype(str)
    df_total.columns.values[1] = 'value'
    return df_total

def census_download_wrapper (variable_file):
    dtypes = {
    'Variable' : str,
    'Code': str,
    'Category': str,
    'Datasource': str,
    'CodeNumber':str,
    'Year':str,
    'census_geom_year':str,
    'GeometryLevel':str
    }


    variables = pd.read_csv(variable_file,dtype=dtypes)

    #Loop through this?
    df_values=pd.DataFrame()
    for index, row in variables.iterrows():
        print(index)
        
        df = get_variable_data(row['Year'], row['Datasource Name'],row['GeometryLevel'],row['CodeNumber'],row['Variable'], census_api_key, row['census_geom_year'], tahoe_geometry, row['Category'])
        
        df_values = create_or_append_df(df_values, df)
    return df_values

def census_download_wrapper_non_tahoe(variable_file):
    dtypes = {
    'Variable' : str,
    'Code': str,
    'Category': str,
    'Datasource': str,
    'CodeNumber':str,
    'Year':str,
    'census_geom_year':str,
    'GeometryLevel':str
    }
    variables = pd.read_csv(variable_file,dtype=dtypes)

    #Loop through this?
    df_values=pd.DataFrame()
    for index, row in variables.iterrows():
        print(index)
        df = get_non_tahoe_data(row['Year'], row['Datasource Name'], row['CodeNumber'], row['Variable'], census_api_key, row['census_geom_year'], row['Category'])
        df_values = create_or_append_df(df_values, df)
    return df_values

def load_variable_multiple_year(year_range, dataset, geometry_return, variable, variablename, census_api_key, tahoe_geometry, variable_category):
    df=pd.DataFrame()
    df_return=pd.DataFrame()
    #year_range = [str(num) for num in range(year_start, year_end+1)]
    for year in year_range:
        if year in ['2020', '2021', '2022']:
            census_geom_year = '2020'
        else:
            census_geom_year = '2010'
        df = get_variable_data(year,dataset,geometry_return,variable,variablename,census_api_key, census_geom_year, tahoe_geometry, variable_category)
        print(len(df))
        df_return = create_or_append_df(df_return, df)
        
    return df_return


def calculate_median_value(df, bin_column, sort_column, count_column, category_field, category,grouping_variables, cumulative_sorting_variables):
        # Create a new DataFrame to avoid modifying the original one
    #change value to count column
    #Do we need to handle excluding non-tahoe things here or should we do it in the input?
    summary_df = df.copy()
    summary_df[count_column]=summary_df[count_column].astype(int)
    #summary_df=summary_df.loc[summary_df[count_column]!='510']
    summary_df = summary_df.groupby(grouping_variables)[count_column].sum()
    summary_df = summary_df.reset_index()
    #This handles -6666 values that they sometimes add for unknown data
    summary_df = summary_df.loc[summary_df[count_column]>=0]
    
    
    summary_df= summary_df.loc[summary_df[category_field]==category]
    # Sort the DataFrame based on the variable name column
    # This depends on the fact that census variables start with the lowest value and go up 
    #This needs to all be rethought to have some kind of window function to handle multiple years
    summary_df.sort_values(by=sort_column, inplace=True)
    summary_df = summary_df.reset_index()
    
    # Extract lower and upper limits from bin categories
    #This uses regex to find numbers and removes commas to make numbers numbers 
    pattern = r'(\d+[\d,]*)'
    summary_df['temp'] = summary_df[bin_column].str.replace(',', '').str.findall(pattern)
    #Looks for values that have two numbers and puts empty placeholders for the ones that only have one (upper and lower)
    summary_df[['Lower', 'Upper']] = summary_df['temp'].apply(lambda x: pd.Series(x[:2]) if len(x) == 2 else pd.Series([None, None]))
    summary_df['Lower'] = summary_df['Lower'].astype(float)
    summary_df['Upper'] = summary_df['Upper'].astype(float)
    # Handle first category
    
    first_upper = float(summary_df['temp'].iloc[0][0])
    low_variable_name = summary_df[bin_column].iloc[0]

    summary_df.loc[summary_df[bin_column]==low_variable_name,'Lower'] = 0  # Set lower value to 0
    summary_df.loc[summary_df[bin_column]==low_variable_name,'Upper'] = first_upper

    
    # Handle last category
    
    last_lower = float(summary_df['temp'].iloc[-1][0])
    upper_variable_name = summary_df[bin_column].iloc[-1]
    summary_df.loc[summary_df[bin_column]==upper_variable_name,'Lower'] = last_lower
    summary_df.loc[summary_df[bin_column]==upper_variable_name,'Upper'] = np.inf  # Set upper value to infinity
    summary_df[count_column]= summary_df[count_column].astype(float)   
    # Calculate cumulative count
    cumulative_grouping_variables = grouping_variables

    cumulative_grouping_variables.remove(bin_column)
    cumulative_grouping_variables.remove(sort_column)

    #Update this to be parameterized
    
    summary_df.sort_values(by=cumulative_sorting_variables, inplace=True)
    summary_df = summary_df.reset_index()
    summary_df['cumulative_sum'] = summary_df.groupby(cumulative_grouping_variables, as_index=False)[count_column].cumsum()
    summary_df['TotalSum'] = summary_df.groupby(cumulative_grouping_variables, as_index=False)[count_column].transform('sum')
    summary_df['previous_cumulative'] = summary_df['cumulative_sum'].shift()

    summary_df = summary_df.loc[summary_df['cumulative_sum']>=(summary_df['TotalSum']/2)].groupby(cumulative_grouping_variables, as_index=False).first()

    summary_df['cumulative_difference'] = summary_df['TotalSum']  / 2 - summary_df['previous_cumulative']
    summary_df['interpolation_ratio'] = summary_df['cumulative_difference'] /  (summary_df['cumulative_sum']- summary_df['previous_cumulative'])
    summary_df['median_value'] = summary_df['Lower'] + summary_df['interpolation_ratio'] * (summary_df['Upper'] - summary_df['Lower'])
    
    
    return summary_df

def categorize_values(census_df, categories_df, category_column, grouping_prefix):
 
    census_df['value'] = census_df['value'].astype(float)
    joined_data = census_df.merge(categories_df, on = 'variable_code', how = 'left')
    joined_data.sort_values(by='variable_code', inplace=True)
    #This will get rid of any extra columns in the category_csv
    group_columns = [column for column in census_df if column not in ['value', 'variable_code', 'variable_name', 'MarginOfError','OBJECTID']]
    group_columns.append(category_column)
    group_columns.append(grouping_prefix)
                         
    print(group_columns)
    grouped_data = joined_data.groupby(group_columns, as_index=False, dropna=False).agg({'value':'sum',
                                                                           'variable_code':lambda x: ', '.join(x)})
    grouped_data['variable_code'] = grouped_data[grouping_prefix]+ ": " + grouped_data['variable_code']
    #Need to return this formatted for appending to the table - need to get locations of variable_code and variable name, 
    #add them in as columns in those locations and then populate them with category column nanme
    var_code_col_location = census_df.columns.get_loc('variable_code')
    var_name_col_location = census_df.columns.get_loc('variable_name')
    var_moe_col_location = census_df.columns.get_loc('MarginOfError')
    grouped_data.insert(var_moe_col_location, 'MarginOfError', '')
    #grouped_data.insert(var_code_col_location, 'variable_code','Grouped Value')
    grouped_data.insert(var_name_col_location, 'variable_name','')
    #grouped_data['variable_code'] = grouped_data['variable_code'] +  '_Grouped'
    grouped_data['variable_name'] = grouped_data[category_column]
    grouped_data['dataset']= grouping_prefix + grouped_data['dataset']
    grouped_data['variable_category']= grouping_prefix +  grouped_data['variable_category'] 
    columns_to_keep = [column for column in census_df if column not in ['OBJECTID']]
    grouped_data= grouped_data[columns_to_keep]
    return grouped_data

def sum_across_levels(df, variable_code, category_name):
    print(variable_code)
    filtered_df = df.loc[(df['variable_code']==variable_code)]
    basin_summary = filtered_df.groupby([ 'dataset', 'sample_level', 'variable_name', 'variable_code', 'variable_category', 'year_sample'], as_index=False).sum(['value'])
    county_summary = filtered_df.groupby(['dataset', 'sample_level', 'variable_name', 'variable_code','variable_category', 'year_sample', 'county_name'], as_index=False).sum(['value'])
    north_south_summary = filtered_df.groupby(['dataset', 'sample_level', 'variable_name', 'variable_code','variable_category', 'year_sample', 'north_south'], as_index=False).sum(['value'])
    state_summary = filtered_df.groupby(['dataset', 'sample_level', 'variable_name', 'variable_code','variable_category', 'year_sample', 'state_name'], as_index=False).sum(['value'])
    #basin_summary.rename(columns = {'variable_code': 'Code', 'year_sample': 'Year'})
    basin_summary['Geography'] = 'Basin'
    county_summary['Geography'] = county_summary['county_name'] 
    north_south_summary['Geography'] = north_south_summary['north_south']
    state_summary['Geography'] = state_summary['state_name']
    columns_to_keep = ['variable_code','variable_name','variable_category', 'value', 'Geography', 'year_sample', 'dataset', 'sample_level']
    basin_summary= basin_summary[columns_to_keep]
    county_summary = county_summary[columns_to_keep]
    north_south_summary = north_south_summary[columns_to_keep]
    state_summary = state_summary[columns_to_keep]
    combined_summary = pd.concat([basin_summary, county_summary, north_south_summary, state_summary], ignore_index=True)
    #if neighborhood_yn == 'Yes':
    #    neighborhood_summary = filtered_df.groupby(['dataset', 'sample_level', 'variable_name', 'variable_code', 'year_sample', 'NEIGHBORHOOD'], as_index=False).sum(['value'])
        #basin_summary.rename(columns = {'variable_code': 'Code', 'year_sample': 'Year'})
    #    neighborhood_summary['Geography'] = neighborhood_summary['NEIGHBORHOOD']
    #    combined_summary = pd.concat([combined_summary, neighborhood_summary], ignore_index=True)
    combined_summary['Category'] = combined_summary['variable_category']
    combined_summary.drop(columns = ['variable_category'], inplace=True)
    return combined_summary
def sum_multiple_variables(df, variable_list, variable_category):
    df_values=pd.DataFrame()
    for variable in variable_list:
        print(variable)
        summed_df = sum_across_levels(df,variable, variable_category)
        
        df_values = create_or_append_df(df_values, summed_df)
    return df_values